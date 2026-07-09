# jobnotify

서버에서 오래 걸리는 파이썬 작업(학습·샘플링·평가 등)이 **끝나면 Telegram으로 알림**을 보내는 작은 모듈.

- 의존성 **0개** — 파이썬 표준 라이브러리(`urllib`)만 사용
- 알림 전송이 실패해도 **원래 작업은 절대 죽지 않음** (stderr 경고만)
- 토큰·chat_id는 **환경변수로만** 주입 — 소스에 개인정보 하드코딩 없음
- 자격증명이 없으면 **조용히 no-op** (로컬 개발 시 안전)

---

## 설치 (다른 레포에서 import해서 쓰기)

이 레포를 소비하는 레포(B/C/D…)에 **소스를 복사하지 않습니다.** pip로 설치하면 이 코드는
`site-packages`에 들어가고, 소비 레포 작업 트리에는 아무 파일도 생기지 않으므로 실수로 커밋될 일이 없습니다.

```bash
# SSH (권장)
pip install "git+ssh://git@github.com/<USER>/jobnotify.git"

# 또는 HTTPS
pip install "git+https://github.com/<USER>/jobnotify.git"

# 특정 버전 태그 고정
pip install "git+ssh://git@github.com/<USER>/jobnotify.git@v0.1.0"
```

Docker로 실행한다면 Dockerfile의 `pip install` 블록에 위 한 줄을 추가하면 됩니다.

---

## Telegram 준비 (1회)

1. Telegram에서 **@BotFather** 대화 → `/newbot` → 안내에 따라 봇 생성 → **봇 토큰** 발급.
2. 방금 만든 봇을 찾아 대화창을 열고 **아무 메시지나 한 번 전송** (봇이 내 chat을 알게 하기 위함).
3. 브라우저에서 아래 주소를 열어 응답의 `result[].message.chat.id` 값을 확인 → 이게 **chat_id**.
   ```
   https://api.telegram.org/bot<봇토큰>/getUpdates
   ```
4. 서버에 환경변수로 주입:
   ```bash
   export JOBNOTIFY_TELEGRAM_TOKEN="123456789:AA...."
   export JOBNOTIFY_TELEGRAM_CHAT_ID="000000000"
   ```
   또는 `.env` 사용:
   ```bash
   cp .env.example .env      # 값 채우기 (.env 는 gitignore 되어 커밋 안 됨)
   set -a; source .env; set +a
   ```
   또는 Docker:
   ```bash
   docker run -e JOBNOTIFY_TELEGRAM_TOKEN -e JOBNOTIFY_TELEGRAM_CHAT_ID ...
   ```

---

## 사용법

### (a) context manager — 가장 추천

성공·실패를 모두 알리고, 예외는 그대로 다시 던집니다(로그/종료코드 영향 없음).

```python
from jobnotify import notify_scope

if __name__ == "__main__":
    with notify_scope("train.py / GridLayoutVAE"):
        main(resume, epochs, patience)
```

### (b) decorator

```python
from jobnotify import notify_on_finish

@notify_on_finish("ldm train")
def main(...):
    ...
```

### (c) 단발 알림

```python
from jobnotify import notify

notify("epoch 50 도달, val_loss=0.012")
```

성공 메시지 예시:

```
✅ Job finished: train.py / GridLayoutVAE
host: gpu-server-01
elapsed: 3h 12m 40s
start: 2026-07-09 01:10:22
end:   2026-07-09 04:23:02
```

실패 시에는 ❌ 와 예외 타입·메시지·traceback 마지막 줄들이 함께 전송됩니다.

---

## 환경변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `JOBNOTIFY_TELEGRAM_TOKEN` | ✅ | BotFather 봇 토큰 |
| `JOBNOTIFY_TELEGRAM_CHAT_ID` | ✅ | 알림 받을 chat id |
| `JOBNOTIFY_JOB_NAME` | | 코드에서 job 이름을 안 넘길 때 쓰는 기본 라벨 |
| `JOBNOTIFY_DISABLE` | | `1`이면 모든 알림 끄기 |

토큰/chat_id 중 하나라도 없으면 알림은 조용히 비활성화됩니다.

---

## 보안

- 실제 토큰은 **절대 커밋하지 마세요.** `.env`는 `.gitignore`에 등록되어 있고, 저장소에는
  placeholder만 담긴 `.env.example`만 올라갑니다.
- 소스코드는 자격증명을 오직 환경변수에서만 읽습니다 — 하드코딩된 비밀값이 없습니다.

---

## 확장 (다른 메신저 추가)

`src/jobnotify/backends.py`의 `Backend`를 상속해 새 백엔드(Discord/Slack 등)를 만들고
`build_backends()`에 등록하면 공개 API 변경 없이 채널을 추가할 수 있습니다.
