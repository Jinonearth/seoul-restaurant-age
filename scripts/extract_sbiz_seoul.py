"""상가(상권)정보 zip에서 서울 파일만 꺼내 UTF-8 CSV로 저장. 연도마다 파일명 인코딩·본문 인코딩이 달라 둘 다 처리한다.

사용: python extract_sbiz_seoul.py <zip> <out.csv>
"""
import sys, zipfile

src, out = sys.argv[1], sys.argv[2]
sys.stdout.reconfigure(encoding="utf-8")
def name(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")


def find_seoul(z):
    """서울 CSV를 찾는다. 2019~2022년 파일은 zip 안에 zip이 들어 있어 안쪽까지 내려간다."""
    for i in z.infolist():
        n = name(i)
        if "서울" in n and n.lower().endswith(".csv"):
            return n, z.read(i)
    for i in z.infolist():
        if name(i).lower().endswith(".zip"):
            import io
            found = find_seoul(zipfile.ZipFile(io.BytesIO(z.read(i))))
            if found:
                return found
    return None


found = find_seoul(zipfile.ZipFile(src))
if not found:
    sys.exit("서울 CSV를 찾지 못함")
member_name, raw = found
for enc in ("utf-8-sig", "cp949"):
    try:
        text = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
else:
    text = raw.decode("cp949", errors="replace")
    enc = "cp949(replace)"
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(member_name, enc, f"{len(raw) / 1e6:.0f}MB", "| header:", text.split("\n", 1)[0][:200])
