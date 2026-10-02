"""Code 128 barcode encoder (pure Python, no dependencies).

Emits SVG so labels print crisply at any size and need no external libraries or fonts.

Pattern data is the canonical ISO/IEC 15417 table: each symbol is 6 alternating
bar/space elements totalling 11 modules, plus the 13-module stop pattern. Two
independent transcriptions of the table are stored below (module string and run
widths) and cross-checked by ``self_test()`` at import time, so a typo can never
silently produce an unreadable barcode.

Code set B is used for alphanumeric data; pure digit strings use the more compact
code set C (two digits per symbol).
"""
from __future__ import annotations

# 11-module module strings, values 0..106 (106 = stop without the trailing bar)
MODULES: list[str] = [
    "11011001100", "11001101100", "11001100110", "10010011000", "10010001100",  # 0-4
    "10001001100", "10011001000", "10011000100", "10001100100", "11001001000",  # 5-9
    "11001000100", "11000100100", "10110011100", "10011011100", "10011001110",  # 10-14
    "10111001100", "10011101100", "10011100110", "11001110010", "11001011100",  # 15-19
    "11001001110", "11011100100", "11001110100", "11101101110", "11101001100",  # 20-24
    "11100101100", "11100100110", "11101100100", "11100110100", "11100110010",  # 25-29
    "11011011000", "11011000110", "11000110110", "10100011000", "10001011000",  # 30-34
    "10001000110", "10110001000", "10001101000", "10001100010", "11010001000",  # 35-39
    "11000101000", "11000100010", "10110111000", "10110001110", "10001101110",  # 40-44
    "10111011000", "10111000110", "10001110110", "11101110110", "11010001110",  # 45-49
    "11000101110", "11011101000", "11011100010", "11011101110", "11101011000",  # 50-54
    "11101000110", "11100010110", "11101101000", "11101100010", "11100011010",  # 55-59
    "11101111010", "11001000010", "11110001010", "10100110000", "10100001100",  # 60-64
    "10010110000", "10010000110", "10000101100", "10000100110", "10110010000",  # 65-69
    "10110000100", "10011010000", "10011000010", "10000110100", "10000110010",  # 70-74
    "11000010010", "11001010000", "11110111010", "11000010100", "10001111010",  # 75-79
    "10100111100", "10010111100", "10010011110", "10111100100", "10011110100",  # 80-84
    "10011110010", "11110100100", "11110010100", "11110010010", "11011011110",  # 85-89
    "11011110110", "11110110110", "10101111000", "10100011110", "10001011110",  # 90-94
    "10111101000", "10111100010", "11110101000", "11110100010", "10111011110",  # 95-99
    "10111101110", "11101011110", "11110101110", "11010000100", "11010010000",  # 100-104
    "11010011100", "11000111010",                                              # 105, 106
]

# The same table expressed as run widths (transcribed independently as a cross-check)
WIDTHS: list[str] = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
    "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
    "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
    "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
    "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
    "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
    "211214", "211232", "233111",
]

START_A, START_B, START_C, STOP = 103, 104, 105, 106
# 13 modules = the 11-module stop symbol followed by its 2-module terminating bar
STOP_PATTERN = "11000111010" + "11"
QUIET_ZONE_MODULES = 10

assert len(MODULES) == 107 and len(WIDTHS) == 107, "Code 128 table must have 107 entries"


# --------------------------------------------------------------------- checks
def _runs(bits: str) -> list[int]:
    """Run lengths of a module string, e.g. '10100011000' -> [1,1,1,3,2,3]."""
    out: list[int] = []
    current, count = bits[0], 0
    for ch in bits:
        if ch == current:
            count += 1
        else:
            out.append(count)
            current, count = ch, 1
    out.append(count)
    return out


def self_test() -> list[str]:
    """Validate the code table. Returns a list of problems (empty = healthy)."""
    problems: list[str] = []
    if len(set(MODULES)) != 107:
        problems.append("module patterns are not unique")
    for value, bits in enumerate(MODULES):
        if len(bits) != 11:
            problems.append(f"value {value}: pattern is {len(bits)} modules, expected 11")
            continue
        if bits[0] != "1" or bits[-1] != "0":
            problems.append(f"value {value}: must start with a bar and end with a space")
        widths = _runs(bits)
        if len(widths) != 6:
            problems.append(f"value {value}: {len(widths)} runs, expected 6")
            continue
        if sum(widths) != 11:
            problems.append(f"value {value}: widths sum to {sum(widths)}, expected 11")
        bars, spaces = widths[0::2], widths[1::2]
        if sum(bars) % 2 != 0:
            problems.append(f"value {value}: bar widths must sum to an even number")
        if sum(spaces) % 2 != 1:
            problems.append(f"value {value}: space widths must sum to an odd number")
        if any(w < 1 or w > 4 for w in widths):
            problems.append(f"value {value}: element width outside 1-4 modules")
        if "".join(str(w) for w in widths) != WIDTHS[value]:
            problems.append(f"value {value}: module string and width table disagree "
                            f"({''.join(str(w) for w in widths)} vs {WIDTHS[value]})")
    if MODULES[START_B] != "11010010000":
        problems.append("start B pattern is wrong")
    if MODULES[START_C] != "11010011100":
        problems.append("start C pattern is wrong")
    if MODULES[STOP] + "11" != STOP_PATTERN:
        problems.append("stop pattern is wrong")
    return problems


def _checksum(values: list[int]) -> int:
    """Weighted modulo-103 check symbol (start symbol counts as the first value)."""
    total = values[0]
    for weight, value in enumerate(values[1:], start=1):
        total += weight * value
    return total % 103


def _encode_values(data: str) -> list[int]:
    """Pick a code set and return the symbol values (without checksum/stop)."""
    digits = data.isdigit()
    # code set C: two digits per symbol, worth it for 4+ leading digits in even groups
    if digits and len(data) >= 4 and len(data) % 2 == 0:
        values = [START_C]
        for i in range(0, len(data), 2):
            values.append(int(data[i:i + 2]))
        return values
    if not data:
        raise ValueError("nothing to encode")
    values = [START_B]
    for ch in data:
        code = ord(ch)
        if not 32 <= code <= 126:
            raise ValueError(f"character {ch!r} cannot be encoded in code set B")
        values.append(code - 32)
    return values


def code128_bits(data: str) -> str:
    """Return the full module string ('1' = bar) for the given data."""
    values = _encode_values(str(data))
    values.append(_checksum(values))
    bits = "".join(MODULES[v] for v in values) + STOP_PATTERN
    quiet = "0" * QUIET_ZONE_MODULES
    return quiet + bits + quiet


def code128_svg(data: str, *, module_width: float = 0.33, height: float = 13.0,
                show_text: bool = True, text: str | None = None,
                font_size: float = 3.0) -> str:
    """Render the barcode as a standalone SVG string (sizes in millimetres)."""
    bits = code128_bits(data)
    width = len(bits) * module_width
    text_height = font_size + 1.6 if show_text else 0
    total_height = height + text_height
    rects: list[str] = []
    position = 0          # module cursor — must advance even over quiet zone and spaces
    i = 0
    while i < len(bits):
        run = bits[i]
        j = i
        while j < len(bits) and bits[j] == run:
            j += 1
        if run == "1":
            rects.append(f'<rect x="{position * module_width:.3f}" y="0" '
                         f'width="{(j - i) * module_width:.3f}" height="{height:.2f}"/>')
        position += j - i
        i = j
    label = text if text is not None else str(data)
    text_el = ""
    if show_text:
        text_el = (f'<text x="{width / 2:.3f}" y="{height + font_size + 0.4:.2f}" '
                   f'text-anchor="middle" font-family="monospace" '
                   f'font-size="{font_size:.2f}" fill="#000">{_xml(label)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}mm" '
            f'height="{total_height:.2f}mm" viewBox="0 0 {width:.3f} {total_height:.3f}">'
            f'<rect width="100%" height="100%" fill="#fff"/><g fill="#000">'
            f'{"".join(rects)}</g>{text_el}</svg>')


def _xml(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def is_encodable(data: str) -> bool:
    try:
        code128_bits(data)
        return True
    except ValueError:
        return False
