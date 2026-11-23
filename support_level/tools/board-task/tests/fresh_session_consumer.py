#!/usr/bin/env python3
"""Fresh Python receipt consumer for isolated fixtures, never hardware."""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import sys
from unittest.mock import patch

tool = Path(__file__).resolve().parents[1] / 'board-task-mcp'
spec = importlib.util.spec_from_loader('consumer', SourceFileLoader('consumer', str(tool)))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
case, fixture_tool = map(Path, sys.argv[1:])
with patch.object(m.subprocess, 'run', side_effect=AssertionError('no processes')), \
     patch.object(m.subprocess, 'Popen', side_effect=AssertionError('no processes')):
    m.CASE = case
    m.TOOL_DIR = fixture_tool
    m.TASK = m.read_task(case, fixture_tool / 'profiles', m.OPS)
    m.BOARD = m.TASK['profile_data']['controller_identity']['bcu_board']
    m.ADAPTER = m.TASK['profile_data']['controller_identity']['ftdi_serial']
    binding = m.load_case_artifact()
    m.verify_case_software_state(binding)
    receipt, digest = m.load_usb_identity_receipt(binding)
    print(json.dumps({'case_id': receipt['case_id'], 'serial': receipt['usb']['serial'],
                      'receipt_sha256': digest, 'hardware_calls': 0}))
