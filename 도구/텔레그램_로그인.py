# -*- coding: utf-8 -*-
"""
텔레그램 첫 로그인 — 사람이 터미널에서 한 번만 돌린다.

  python 도구/텔레그램_로그인.py

전화번호(+8210…) · 텔레그램 앱으로 온 인증번호 · (켜 두었다면) 2단계 비밀번호를 물어본다. 입력은 텔레그램 서버로만 가고 어디에도 적지 않는다.
로그인이 되면 세션 파일이 %LOCALAPPDATA%\\기업추적\\telegram.session 에 생긴다 — 내 계정 전체 권한이니 남에게 주지 말고,
구글 드라이브 같은 동기화 폴더로 옮기지 않는다. 그 뒤로는 뷰어가 이 세션으로 리포트 채널만 읽는다.
끝나면 리포트로 읽을 채널 목록을 보여 준다 — 원하는 채널이 없으면 텔레그램 앱에서 그 채널에 가입(구독)하거나 .env 에 TELEGRAM_CHANNELS 를 적는다.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import 리포트 as R  # noqa: E402


async def main():
    from telethon import TelegramClient
    api_id, api_hash = R._creds()
    os.makedirs(R.SESSION_DIR, exist_ok=True)
    async with TelegramClient(R.SESSION, api_id, api_hash) as client:
        await client.start()               # 전화번호 · 인증번호 · 2단계 비밀번호를 터미널에서 묻는다
        me = await client.get_me()
        print("로그인 됨 — %s" % (me.first_name or "내 계정"))
    try:
        R.collect(list_only=True)
    except Exception as e:
        print("채널 목록을 못 읽었습니다:", e)


if __name__ == "__main__":
    asyncio.run(main())
