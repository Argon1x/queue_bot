import sys
sys.path.insert(0, "..")

from permissions import is_admin


def test_admin_in_list():
    assert is_admin(5121769595)

def test_admin_not_in_list():
    assert not is_admin(999)

def test_admin_empty_id_does_not_crash():
    assert not is_admin(0)
