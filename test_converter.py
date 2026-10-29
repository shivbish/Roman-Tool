"""Run with:  python test_converter.py   (or: pytest)"""
import json
from converter import convert, parse_exceptions, capitalize_sentences, fix_srt_case, convert_srt, looks_like_srt

CASES = {
    "ਪੰਜਾਬੀ": "punjabi", "ਮੈਂ": "main", "ਪੱਕਾ": "pakka", "ਮਿੱਟੀ": "mitti",
    "ਸਮਝ": "samajh", "ਕਰਨਾ": "karna", "ਘਰ": "ghar", "ਪਾਣੀ": "pani",
    "ਠੀਕ": "thik", "ਨਹੀਂ": "nahin", "ਪਿਆਰ": "piyaar", "ਕਮਲ": "kamal",
    "ਅਕਾਲ": "akal", "ਦਿਲ": "dil", "ਚਲਦਾ": "chalda", "ਜਵਾਨ": "javan",
    "ਪ੍ਰੇਮ": "prem", "ਹੈ": "hai", "ਕੀ": "ki", "ਸੁਣਨਾ": "sunna",
    "ਖ਼ਬਰ": "khabar", "ਤੁਸੀਂ": "tusi", "ਸ਼ਹਿਰ": "shehar", "੨੦੨੬": "2026",
    "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ": "sat sri akal", "ਵਿੱਚ": "vich",
    "ਤੁਸੀਂ ਕਿਵੇਂ ਹੋ?": "tusi kiven ho?",
    "Hello ਪੰਜਾਬ": "Hello punjab",
}

def test_cases():
    for src, want in CASES.items():
        assert convert(src) == want, f"{src!r}: got {convert(src)!r}, want {want!r}"

def test_long_vowels():
    assert convert("ਪੱਕਾ", long_vowels=True) == "pakkaa"
    assert convert("ਠੀਕ", long_vowels=True) == "theek"

def test_parse_json_and_python():
    assert parse_exceptions('{"ਘਰ": "ghar-ji"}') == {"ਘਰ": "ghar-ji"}
    assert parse_exceptions("{'ਘਰ': 'ghar-ji'}") == {"ਘਰ": "ghar-ji"}
    assert parse_exceptions('# my words\nEXCEPTIONS = {"ਘਰ": "ghar-ji"}\n') == {"ਘਰ": "ghar-ji"}
    assert parse_exceptions('\ufeff{"ਘਰ": "x"}') == {"ਘਰ": "x"}

def test_parse_rejects_bad_input():
    for bad in ["", "[1, 2]", '{"a": 1}', "x = 5", "__import__('os').system('dir')",
                "EXCEPTIONS = {'a': open('f').read()}", "{broken"]:
        try:
            parse_exceptions(bad)
        except ValueError:
            continue
        raise AssertionError(f"should have been rejected: {bad!r}")

def test_custom_exceptions_override():
    assert convert("ਘਰ ਦਿਲ", exceptions={"ਘਰ": "ghar-ji"}) == "ghar-ji dil"

def test_capitalize():
    assert capitalize_sentences("sat sri akal! tusi kiven ho? main theek han. dhanvad") == \
        "sat sri akal! Tusi kiven ho? Main theek han. Dhanvad"
    assert capitalize_sentences('ho? "main theek han." (hor) ok') == 'ho? "Main theek han." (Hor) ok'
    assert capitalize_sentences("price 3.5 rupay. ok") == "price 3.5 rupay. Ok"   # no split on decimals
    assert capitalize_sentences("wait... ok") == "wait... Ok"
    assert capitalize_sentences("ek\ndo") == "ek\ndo"          # new line alone does not capitalise
    assert capitalize_sentences("ek.\ndo") == "ek.\nDo"        # but a line after a full stop does
    assert capitalize_sentences("first. second") == "first. Second"
    assert convert("ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ! ਤੁਸੀਂ ਕਿਵੇਂ ਹੋ? ਮੈਂ ਠੀਕ ਹਾਂ।", capitalize=True) == \
        "sat sri akal! Tusi kiven ho? Main thik han."
    assert convert("ਮੈਂ ਠੀਕ ਹਾਂ। ਤੁਸੀਂ?").startswith("main")
    assert convert("ਮੈਂ ਠੀਕ ਹਾਂ। ਤੁਸੀਂ?") == "main thik han. tusi?"   # off by default

def test_fix_srt_case():
    srt = ("26\n00:04:02,120 --> 00:04:04,960\nEhnu  ikk  bura  supna  samajh\n"
           "Ke  bhull  kyun  nahi  jande  tusi?\n\n"
           "27\n00:04:06,920 --> 00:04:08,120\nmain  taan  bhull  jaunga\n")
    assert fix_srt_case(srt) == srt.replace("Ke  bhull", "ke  bhull").replace("main  taan", "Main  taan")
    # subtitle tags, {\an8}, and Windows line endings
    t = ("1\r\n00:00:01,000 --> 00:00:02,000\r\n<i>tusi kiven ho?</i>\r\n<i>main theek han.</i>\r\n\r\n"
         "2\r\n00:00:03,000 --> 00:00:04,000\r\n{\\an8}tusi kithe ho\r\nKe nahi\r\n")
    want = ("1\r\n00:00:01,000 --> 00:00:02,000\r\n<i>tusi kiven ho?</i>\r\n<i>Main theek han.</i>\r\n\r\n"
            "2\r\n00:00:03,000 --> 00:00:04,000\r\n{\\an8}Tusi kithe ho\r\nke nahi\r\n")
    assert fix_srt_case(t) == want
    # capital after . ? ! inside a line, even before a tag
    assert fix_srt_case("1\n00:00:01,000 --> 00:00:02,000\nho? <i>main</i> han. ok\n") == \
        "1\n00:00:01,000 --> 00:00:02,000\nho? <i>Main</i> han. Ok\n"
    # a text line that is only a number is text, not a cue number
    assert fix_srt_case("1\n00:00:01,000 --> 00:00:02,000\nho.\n2024\n") == \
        "1\n00:00:01,000 --> 00:00:02,000\nho.\n2024\n"

def test_convert_srt():
    src = ("\ufeff1\n00:00:01,000 --> 00:00:02,000\nਤੁਸੀਂ ਕਿਵੇਂ ਹੋ?\nਮੈਂ ਠੀਕ ਹਾਂ।\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\nਤੁਸੀਂ ਕਿੱਥੇ ਹੋ\nਪੰਜਾਬ ਵਿੱਚ?\n")
    got = convert_srt(src)
    assert got == ("1\n00:00:01,000 --> 00:00:02,000\ntusi kiven ho?\nMain thik han.\n\n"
                   "2\n00:00:03,000 --> 00:00:04,000\nTusi kitthe ho\npunjab vich?\n"), got
    got = convert_srt(src, exceptions={"ਹਾਂ": "haan"}, capitalize=False)
    assert "main thik haan." in got and "tusi kitthe ho" in got
    assert convert_srt(src.replace("\n", "\r\n")).count("\r\n") == src.count("\n")

def test_looks_like_srt():
    assert looks_like_srt("1\n00:00:01,000 --> 00:00:02,000\nਮੈਂ")
    assert looks_like_srt("1\r\n00:00:01.000 --> 00:00:02.000\r\nhi")
    assert not looks_like_srt("ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ! 10:30 ਵਜੇ ਮਿਲਾਂਗੇ")
    assert not looks_like_srt("")

if __name__ == "__main__":
    test_cases(); test_long_vowels()
    test_parse_json_and_python(); test_parse_rejects_bad_input(); test_custom_exceptions_override(); test_capitalize(); test_fix_srt_case(); test_convert_srt(); test_looks_like_srt()
    print("All checks passed")
