"""S3 changelog/<release>/theme=places 의 파티션별 파일 수·용량 요약."""
import sys, re, urllib.request, collections
B = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
for rel in sys.argv[1:]:
    sizes, token = collections.Counter(), None
    while True:
        url = f"{B}/?list-type=2&prefix=changelog/{rel}/theme=places/" + (f"&continuation-token={urllib.parse.quote(token)}" if token else "")
        x = urllib.request.urlopen(url).read().decode()
        for key, size in re.findall(r"<Key>([^<]*)</Key>.*?<Size>(\d+)</Size>", x):
            sizes["/".join(key.split("/")[2:-1])] += int(size)
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not m: break
        token = m.group(1)
    print(rel, {k: f"{v/1e6:.0f}MB" for k, v in sorted(sizes.items())})
