import sys, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from btcs_pool.accounting import Accounting

def test_share_duplicate():
    db=tempfile.mktemp(suffix='.sqlite')
    a=Accounting(db)
    assert a.record_share('u','j',1,True) is True
    assert a.record_share('u','j',1,True) is False
    assert a.share_count('u')==1
    a.close()
    os.remove(db)
