import sys
sys.path.insert(0, "..")

from helpers import esc


def test_esc_normal():
    assert esc("hello") == "hello"

def test_esc_html():
    assert esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

def test_esc_quotes():
    assert esc('he"llo') == "he&quot;llo"

def test_esc_ampersand():
    assert esc("a&b") == "a&amp;b"

def test_esc_none():
    assert esc(None) == "None"

def test_esc_emoji():
    assert esc("👋") == "👋"
