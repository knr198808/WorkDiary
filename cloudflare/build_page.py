# page/ 폴더의 화면 파일들을 서버 코드(app_page.js)로 묶음. 페이지를 고친 뒤 실행.
import json, os
d = os.path.dirname(os.path.abspath(__file__))
def rd(n):
    return open(os.path.join(d, "page", n), encoding="utf-8").read()
with open(os.path.join(d, "app_page.js"), "w", encoding="utf-8") as f:
    f.write("// 자동 생성 (build_page.py) — page/ 폴더의 파일을 고치세요\n")
    f.write("export const APP_HTML = " + json.dumps(rd("app.html"), ensure_ascii=False) + ";\n")
    f.write("export const SW_JS = " + json.dumps(rd("sw.js"), ensure_ascii=False) + ";\n")
    f.write("export const ADMIN_HTML = " + json.dumps(rd("admin.html"), ensure_ascii=False) + ";\n")
print("app_page.js 생성")
