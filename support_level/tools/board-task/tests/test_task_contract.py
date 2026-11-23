"""Portable offline tests. All hardware/process boundaries fail unless mocked."""
import copy
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
import subprocess
import sys
from unittest.mock import patch
import yaml

PYTHON_RUN = subprocess.run
PYTHON_POPEN = subprocess.Popen

TOOL = Path(__file__).resolve().parents[1] / 'board-task-mcp'
spec = importlib.util.spec_from_loader('board_offline', SourceFileLoader('board_offline', str(TOOL)))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SERIAL = '0123456789ABCDEF'
BCU = ('Auto recognized the board: imx943evk19b1\nFTDI EEPROM SN: TEST01\n'
       'Board Rev B1\nSoC Info: i.MX943 Rev A0\nMFS5600\ndone\n')
TARGET = {'carrier': 'i.MX943 EVK B1', 'module': 'i.MX943 15x15 SoC A0',
          'ddr': 'LPDDR4', 'software': 'test-release'}
SPL = ('uuu_version 1.2.39\n# installed format\nSDP: boot -f _flash.bin\n'
       'SDPS[-t 10000]: boot -f _flash.bin\nSDPU: delay 1000\n'
       'SDPU: write -f _flash.bin -offset 0x57c00\nSDPU: jump\nSDPU: done\n'
       'SDPV: delay 1000\nSDPV: write -f _flash.bin -skipspl\nSDPV: jump\nSDPV: done\n')


def table(protocol='SDPS', serial=SERIAL, chip=None, vid='0x1FC9', pid=None):
    chip = ('MX943' if protocol == 'SDPS' else '') if chip is None else chip
    pid = pid or ('0x0027' if protocol == 'SDPS' else '0x0152')
    return ('uuu 1.5.243\n\tPath\t Chip\t Pro\t Vid\t Pid\t BcdVersion\t Serial_no\n'
            '\t====================================================================\n'
            f'\t1:1\t {chip}\t {protocol}:\t {vid}\t {pid}\t 0x0001\t {serial}\n')


class ContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.work = self.root / 'work'
        self.tool = self.root / 'tools/board-task'
        (self.tool / 'profiles').mkdir(parents=True)
        profile = {'id': 'fixture', 'executor': 'imx943-a0-lpddr4',
                   'controller_identity': {'bcu_board': 'imx943evk19b1', 'ftdi_serial': 'TEST01'},
                   'artifact_target': {k: TARGET[k] for k in ('carrier', 'module', 'ddr')}}
        (self.tool / 'profiles/fixture.yaml').write_text(yaml.safe_dump(profile))
        self.start_patch(m, 'WORK_ROOT', self.work)
        self.start_patch(m, 'SUPPORT', self.root)
        self.start_patch(m, 'TOOL_DIR', self.tool)
        self.start_patch(m, 'TASK', None)
        self.start_patch(m, 'CURRENT_CASE_ID', '')
        self.start_patch(m, 'IDENTITY', False)
        self.start_patch(m, 'run', side_effect=AssertionError('Hardware call forbidden'))
        self.start_patch(m.subprocess, 'run', side_effect=AssertionError('Process forbidden'))
        self.start_patch(m.subprocess, 'Popen', side_effect=AssertionError('Process forbidden'))
        self.start_patch(m, 'ensure_control_idle', return_value=None)
        self.case = self.make_case('task-alpha', b'alpha-image', 'artifacts/deep/boot.bin')
        m.select_case(self.case.name)

    def start_patch(self, obj, name, *args, **kwargs):
        p = patch.object(obj, name, *args, **kwargs)
        result = p.start()
        self.addCleanup(p.stop)
        return result

    def make_case(self, name, payload, relative):
        case = self.work / name
        (case / 'records').mkdir(parents=True)
        (case / 'state').mkdir()
        path = case / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        (case / 'records/auth.md').write_text('Synthetic test authorization; never a real board grant.')
        artifact = {'key': name + '_boot', 'id': name + '_v1', 'path': relative,
                    'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                    'build_recipe': 'flash_all_no_m71', 'target_module': copy.deepcopy(TARGET)}
        task = {'schema_version': 1, 'profile': 'fixture', 'artifact': artifact,
                'authorization': {'source': 'records/auth.md', 'operations': list(m.OPS),
                                  'max_reset_attempts': 2}}
        (case / 'records/board-task.yaml').write_text(yaml.safe_dump(task))
        component = {'configuration': {'values': {
            'compile_profile.parameter.recipe.value': artifact['build_recipe'],
            'compile_profile.parameter.soc.value': 'iMX94',
            'compile_profile.parameter.silicon_revision.value': 'A0',
            'compile_profile.parameter.lpddr_type.value': 'lpddr4'}},
            'outputs': [{'path': str(path), 'stat': {'size': len(payload)},
                         'sha256': 'sha256:' + artifact['sha256']}]}
        state = {'targets': {'imx-mkimage': {'components': {'imx-mkimage': component}}}}
        (case / 'state/software-state.yaml').write_text(yaml.safe_dump(state))
        return case

    def mutate_task(self, change):
        p = self.case / 'records/board-task.yaml'
        value = yaml.safe_load(p.read_text())
        change(value)
        p.write_text(yaml.safe_dump(value))

    def confirm(self):
        m.IDENTITY = True
        m.IDENTITY_OUTPUT = BCU
        m.IDENTITY_TIME = '2026-11-17T00:00:00+00:00'
        with patch.object(m, 'one_board'), patch.object(m, 'run', return_value=table()):
            return json.loads(m.confirm_case_usb_identity())

    def test_two_unrelated_cases_and_paths(self):
        first = m.load_case_artifact()
        m.verify_case_software_state(first)
        other = self.make_case('ordinary-beta', b'new-version-binary', 'output.bin')
        m.select_case(other.name)
        second = m.load_case_artifact()
        m.verify_case_software_state(second)
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertEqual(second['case_root'], other)

    def test_case_escape(self):
        with self.assertRaises(ValueError):
            m.select_case('../escape')

    def test_task_required(self):
        (self.case / 'records/board-task.yaml').unlink()
        with self.assertRaises(FileNotFoundError):
            m.select_case(self.case.name)

    def test_unknown_fields_refused(self):
        self.mutate_task(lambda t: t.update(command='sudo anything'))
        with self.assertRaises(RuntimeError):
            m.select_case(self.case.name)

    def test_unauthorized_operation(self):
        self.mutate_task(lambda t: t['authorization'].update(operations=['bcu_identity']))
        with self.assertRaisesRegex(RuntimeError, 'not authorized'):
            m.operate('reset_usb', self.case.name)

    def test_unknown_operation_in_manifest(self):
        self.mutate_task(lambda t: t['authorization']['operations'].append('arbitrary_shell'))
        with self.assertRaises(RuntimeError):
            m.select_case(self.case.name)

    def test_probe_without_artifact(self):
        self.mutate_task(lambda t: t.update(artifact=None))
        m.select_case(self.case.name)
        with self.assertRaises(RuntimeError):
            m.load_case_artifact()

    def test_authorization_source_missing(self):
        (self.case / 'records/auth.md').unlink()
        with self.assertRaises(FileNotFoundError):
            m.select_case(self.case.name)

    def test_budget_invalid(self):
        for budget in (0, -1, 1.5, True, None):
            self.mutate_task(lambda t: t['authorization'].update(max_reset_attempts=budget))
            with self.assertRaises(RuntimeError):
                m.select_case(self.case.name)

    def test_legitimate_larger_reset_budget_is_task_input(self):
        self.mutate_task(lambda t: t['authorization'].update(max_reset_attempts=100))
        m.select_case(self.case.name)
        self.assertEqual(m.TASK['authorization']['max_reset_attempts'], 100)

    def test_manifest_change_invalidates_session_identity(self):
        m.IDENTITY = True
        self.mutate_task(lambda t: t['authorization'].update(max_reset_attempts=1))
        m.select_case(self.case.name)
        self.assertFalse(m.IDENTITY)

    def test_wrong_size_and_hash(self):
        for field, value in [('size', 200), ('sha256', 'a' * 64)]:
            with self.subTest(field=field):
                original = (self.case / 'records/board-task.yaml').read_text()
                self.mutate_task(lambda t: t['artifact'].update({field: value}))
                with self.assertRaises(RuntimeError):
                    m.load_case_artifact()
                (self.case / 'records/board-task.yaml').write_text(original)

    def test_profile_change_invalidates_identity(self):
        m.IDENTITY = True
        p = self.tool / 'profiles/fixture.yaml'
        p.write_text(p.read_text().replace('TEST01', 'TEST02'))
        m.select_case(self.case.name)
        self.assertFalse(m.IDENTITY)
        self.assertEqual(m.ADAPTER, 'TEST02')

    def test_output_directory_cannot_escape_case(self):
        outside = self.root / 'external-logs'
        outside.mkdir()
        (self.case / 'logs').rmdir()
        (self.case / 'logs').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'escapes case'):
            m.select_case(self.case.name)

    def test_adapter_lock_is_shared_between_cases(self):
        other = self.make_case('concurrent-task', b'another-image', 'output.bin')
        lock_root = self.root / 'runtime/board-task'
        lock_root.mkdir(parents=True)
        with (lock_root / 'TEST01.lock').open('a') as lock:
            m.fcntl.flock(lock, m.fcntl.LOCK_EX | m.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                m.operate('bcu_list', other.name)

    def test_sd_aliases_share_reset_budget(self):
        self.mutate_task(lambda t: t['authorization'].update(max_reset_attempts=1))
        m.select_case(self.case.name)
        marker = m.next_reset_marker('sd-case-artifact')
        marker.write_text('original SD attempt')
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            m.next_reset_marker('sd')
        self.assertEqual(marker.read_text(), 'original SD attempt')

    def test_path_escape_and_symlink(self):
        outside = self.root / 'outside.bin'
        outside.write_bytes(b'alpha-image')
        (self.case / 'link.bin').symlink_to(outside)
        for path in ('../outside.bin', str(outside), 'link.bin'):
            self.mutate_task(lambda t: t['artifact'].update(path=path))
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                m.load_case_artifact()

    def test_wrong_module(self):
        self.mutate_task(lambda t: t['artifact']['target_module'].update(ddr='LPDDR5'))
        with self.assertRaises(RuntimeError):
            m.load_case_artifact()

    def test_compile_state_mismatch(self):
        p = self.case / 'state/software-state.yaml'
        p.write_text(p.read_text().replace('lpddr4', 'lpddr5'))
        with self.assertRaises(RuntimeError):
            m.verify_case_software_state(m.load_case_artifact())

    def test_confirm_requires_session_identity(self):
        with self.assertRaisesRegex(RuntimeError, 'bcu_identity'):
            m.confirm_case_usb_identity()

    def test_confirm_validate_and_reuse(self):
        self.assertEqual(self.confirm()['status'], 'confirmed')
        binding = m.load_case_artifact()
        receipt, digest = m.load_usb_identity_receipt(binding)
        original = m.case_usb_receipt_path(binding).read_bytes()
        with patch.object(m, 'one_board'), patch.object(m, 'run', return_value=table('FB')):
            self.assertEqual(json.loads(m.confirm_case_usb_identity())['status'], 'reused')
        self.assertEqual(original, m.case_usb_receipt_path(binding).read_bytes())
        m.record_usb_receipt_consumption(binding, receipt, digest, 'test', 'read')
        self.assertTrue((self.case / m.CASE_USB_CONSUMPTION_REL).is_file())

    def test_receipt_refuses_tampering(self):
        self.confirm()
        binding = m.load_case_artifact()
        p = m.case_usb_receipt_path(binding)
        original = json.loads(p.read_text())
        for update in ({'case_id': 'other-case'}, {'scope': 'runtime_pass'}, {'raw_probe': 'invented'}):
            changed = dict(original, **update)
            p.write_text(json.dumps(changed))
            with self.assertRaises(RuntimeError):
                m.load_usb_identity_receipt(binding)

    def test_new_session_can_validate_receipt(self):
        self.confirm()
        m.IDENTITY = False
        m.CURRENT_CASE_ID = ''
        m.select_case(self.case.name)
        receipt, _ = m.load_usb_identity_receipt(m.load_case_artifact())
        self.assertEqual(receipt['usb']['serial'], SERIAL)
        with self.assertRaisesRegex(RuntimeError, 'First run'):
            m.operate('uuu_boot_case_flashbin', self.case.name)

    def test_missing_receipt_blocks_transfer(self):
        with self.assertRaisesRegex(RuntimeError, 'receipt missing'):
            m.uuu_boot_case_flashbin([])

    def test_wrong_live_serial_refuses_reuse(self):
        self.confirm()
        with patch.object(m, 'one_board'), patch.object(m, 'run', return_value=table(serial='FEDCBA9876543210')):
            with self.assertRaises(RuntimeError):
                m.confirm_case_usb_identity()

    def test_usb_rows_positive(self):
        self.assertEqual(m.select_exact_usb_row(table(), 'SDPS')['serial'], SERIAL)
        self.assertEqual(m.select_exact_usb_row(table('FB'), 'FB')['chip'], '')

    def test_usb_negative_boundaries(self):
        samples = [table(chip='MX95'), table(vid='0x1234'), table(pid='0x9999'),
                   table(serial='bad'), table('FB'), 'SDPS MX943 1FC9 0027 ' + SERIAL,
                   table() + table().splitlines()[-1] + '\n']
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(RuntimeError):
                m.select_exact_usb_row(sample, 'SDPS', SERIAL)

    def test_spl_real_and_plain_positive(self):
        m.require_spl_recipe(SPL)
        m.require_spl_recipe(SPL.replace('SDPS[-t 10000]', 'SDPS'))

    def test_spl_negative_boundaries(self):
        for sample in (SPL + 'FB: flash bootloader other\n', SPL + 'XYZ: arbitrary\n',
                       SPL.replace('_flash.bin', 'other.bin'), SPL.replace('SDPV: jump\n', ''),
                       '# SDPS: boot -f _flash.bin\n# SDPV: jump\n',
                       SPL.replace('SDPS[-t 10000]', 'SDPS[-bad]')):
            with self.subTest(sample=sample), self.assertRaises(RuntimeError):
                m.require_spl_recipe(sample)

    def test_reset_marker_retained_review_then_bounded_retry(self):
        marker = m.next_reset_marker('usb')
        marker.write_text('original attempt evidence')
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
            m.next_reset_marker('usb')
        with patch.object(m, 'one_board'), patch.object(m, 'ports_free'), patch.object(m, 'run', return_value='fresh probe'):
            result = json.loads(m.review_reset([]))
        self.assertFalse(result['reset_performed'])
        self.assertEqual(marker.read_text(), 'original attempt evidence')
        second = m.next_reset_marker('usb')
        second.write_text('second attempt evidence')
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            m.next_reset_marker('usb')

    def test_review_refuses_busy_controller(self):
        with patch.object(m, 'ensure_control_idle', side_effect=RuntimeError('busy')):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                m.review_reset([])

    def test_review_refuses_serial_ownership(self):
        with patch.object(m, 'one_board'), patch.object(m, 'ports_free', side_effect=RuntimeError('occupied')):
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                m.review_reset([])

    def test_manifest_does_not_grant_unknown_shell(self):
        result = m.handle({'method': 'tools/call', 'params': {'name': 'run_board_check',
            'arguments': {'case_id': self.case.name, 'operation': 'bcu_identity', 'command': 'shell'}}})
        self.assertTrue(result['isError'])

    def test_storage_completion_requires_evidence(self):
        with self.assertRaises(RuntimeError):
            m.require_case_write_markers('exit 0')
        with self.assertRaises(RuntimeError):
            m.require_completed_case(self.case / 'missing.json', m.load_case_artifact(), 'sd_bootloader')

    @contextmanager
    def transaction(self, ready=True, write_markers=True):
        calls = []
        state = {'protocol': 'SDPS'}
        class Capture:
            pid = 12345
            def __init__(self, argv, **kwargs):
                self.returncode = None if ready else 0
                if ready:
                    Path(argv[argv.index('--ready-file') + 1]).write_text(yaml.safe_dump({
                        'state': 'active', 'pid': self.pid, 'roles': ['a-core', 'sm']}))
            def poll(self): return self.returncode
            def terminate(self): self.returncode = 0
            def wait(self, timeout=None): self.returncode = 0; return 0
        def runner(argv, timeout=15):
            argv = list(map(str, argv))
            calls.append(argv)
            if '-lsusb' in argv: return table(state['protocol'])
            if 'lsftdi' in argv: return 'found: 1\nserial_no: TEST01\n'
            if 'eeprom' in argv: return BCU
            if 'lsbootmode' in argv: return 'usb\nsd\n'
            if 'reset' in argv: return 'reset successfully'
            if '-bshow' in argv:
                if argv[-1] == 'spl': return SPL
                return ('FB: ucmd setenv fastboot_dev mmc\nFB: ucmd mmc dev ' + '$' + '{sd_dev}\n'
                        'FB: flash bootloader _image\nFB: Done\n')
            if '-b' in argv:
                if argv[argv.index('-b') + 1] == 'spl':
                    state['protocol'] = 'FB'
                    return 'transfer finished'
                if write_markers:
                    return ('Start Cmd:FB: ucmd mmc dev ' + '$' + '{sd_dev}\n'
                            'Start Cmd:FB: flash bootloader _image\nStart Cmd:FB: Done\n')
                return 'exit zero but completion unknown'
            return 'mock probe/recover'
        with patch.object(m, 'run', side_effect=runner), patch.object(m, 'ports_free'), \
             patch.object(m.subprocess, 'Popen', Capture), patch.object(m.time, 'sleep'):
            yield calls

    def test_full_mocked_boot_write_reset_chain(self):
        self.confirm()
        with self.transaction() as calls:
            m.LAST_SERIAL = 'root@test:~# '
            m.uuu_boot_case_flashbin([])
            self.assertEqual(m.LAST_SERIAL, '')
            m.uuu_flash_case_bootloader()
            m.LAST_SERIAL = 'root@test:~# '
            m.reset_sd_case([])
            self.assertEqual(m.LAST_SERIAL, '')
        write = json.loads((self.case / (m.CASE_WRITE_RECEIPT + '.completed.json')).read_text())
        self.assertEqual(write['sd_dev'], 1)
        self.assertEqual(write['artifact_sha256'], m.load_case_artifact()['sha256'])
        self.assertTrue(any('sd_dev=1' in argv for argv in calls))
        ledger = yaml.safe_load((self.case / 'state/ledger.yaml').read_text())
        self.assertNotIn('no flashing permitted', ledger['next_action'])
        self.assertTrue((self.case / 'state/reset-sd-case-artifact.attempted.outcome.json').is_file())

    def test_ready_failure_prevents_reset_and_transfer(self):
        self.confirm()
        with self.transaction(ready=False) as calls:
            with self.assertRaisesRegex(RuntimeError, 'READY'):
                m.uuu_boot_case_flashbin([])
            with self.assertRaisesRegex(RuntimeError, 'READY'):
                m.reset_with_capture('usb', [])
        self.assertFalse(any('-b' in argv or 'reset' in argv for argv in calls))

    def test_write_failure_has_attempt_not_completion(self):
        self.confirm()
        with self.transaction(write_markers=False):
            m.uuu_boot_case_flashbin([])
            with self.assertRaisesRegex(RuntimeError, 'completion markers'):
                m.uuu_flash_case_bootloader()
        self.assertTrue((self.case / (m.CASE_WRITE_RECEIPT + '.attempted.jsonl')).is_file())
        self.assertFalse((self.case / (m.CASE_WRITE_RECEIPT + '.completed.json')).exists())
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            m.uuu_flash_case_bootloader()

    def test_fresh_process_validates_persisted_receipt(self):
        self.confirm()
        helper = Path(__file__).with_name('fresh_session_consumer.py')
        with patch.object(subprocess, 'Popen', PYTHON_POPEN):
            result = PYTHON_RUN([sys.executable, '-B', str(helper), str(self.case), str(self.tool)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['case_id'], self.case.name)
        self.assertEqual(value['serial'], SERIAL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
