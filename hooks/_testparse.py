import re

_PASSED_RE = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
_FAILED_RE = re.compile(r"(\d+)\s+(?:failed|failures)", re.IGNORECASE)


def parse_test_output(output, is_error):
    if not isinstance(output, str):
        output = ""
    passed = None
    failed = None
    pm = _PASSED_RE.search(output)
    fm = _FAILED_RE.search(output)
    if pm:
        passed = int(pm.group(1))
    if fm:
        failed = int(fm.group(1))

    if failed is not None and failed > 0:
        outcome = "failed"
    elif is_error:
        outcome = "failed"
    elif passed is not None and (failed is None or failed == 0):
        outcome = "passed"
    else:
        outcome = "unknown"
    return {"test_passed": passed, "test_failed": failed, "test_outcome": outcome}
