# jobnotify

서버에서 오래 걸리는 파이썬 작업(학습·샘플링·평가 등)이 **끝나면 Telegram으로 알림**을 보내는 작은 모듈.

- **시작할 때 1건, 끝날 때 1건** — "a.py가 gpu 0에서 이 커맨드로 시작", "a.py 종료(성공/실패)"
- 알림에 **실험 이름 · GPU · 실행 커맨드**가 함께 찍힘 (어느 실험인지 폰에서 바로 구분)
- 파이썬뿐 아니라 **아무 명령어나 감쌀 수 있음** — `jobnotify -- <커맨드>`
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

알림은 **시작 1건 + 종료 1건**이 옵니다. 종료 알림만 받으려면 `notify_start=False`
(또는 `JOBNOTIFY_NOTIFY_START=0`).

실험 이름을 붙이려면 (GPU·커맨드는 자동으로 들어갑니다):

```python
with notify_scope("train.py / GridLayoutVAE", experiment="kd_pku_cgl"):
    main(...)
```

`experiment=` 를 안 넘기면 `JOBNOTIFY_EXPERIMENT` 환경변수를 씁니다 — 코드를 건드리지 않고
`docker run -e JOBNOTIFY_EXPERIMENT=...` 로 실험마다 라벨을 바꿀 수 있습니다.
시작 시점 알림이 필요하면 `notify_start=True`.

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

### (d) 커맨드 래퍼 (CLI) — 파이썬이 아니어도 됨

`pip install` 하면 `jobnotify` 명령어가 같이 깔립니다. 아무 커맨드 앞에 붙이기만 하면
끝날 때 알림이 옵니다. **자식 프로세스의 출력과 종료코드는 그대로 통과**하므로
기존 스크립트/파이프라인 동작은 바뀌지 않습니다.

```bash
jobnotify -- python -m poster.train --datasets pku
jobnotify -e kd_pku_cgl -n "poster KD" -- python -m poster.train --pseudo out/cgl.jsonl
jobnotify --shell 'cd /work && python train.py && python eval.py'
jobnotify --test          # 토큰·chat_id 설정이 맞는지 확인 (테스트 알림 1건)
```

`python -m jobnotify ...` 도 같은 동작입니다.

| 옵션 | 설명 |
|---|---|
| `-n, --name NAME` | 알림 제목에 쓸 라벨 (기본값: 커맨드에서 유추, 또는 `$JOBNOTIFY_JOB_NAME`) |
| `-e, --experiment NAME` | 실험 id (기본값: `$JOBNOTIFY_EXPERIMENT`) |
| `-g, --gpu TEXT` | 자동 감지된 GPU 설명을 직접 덮어쓰기 |
| `--shell` | 나머지를 셸 한 줄로 실행 (`&&`, 파이프 등) |
| `--no-start` | 시작 알림 끄기 (종료 알림만) |
| `--tail N` | 출력 마지막 N줄을 알림에 첨부 (기본 0 = 캡처 안 함, 출력 그대로 통과) |
| `--no-gpu` | GPU 조회 생략 |
| `--test` | 자격증명 확인용 테스트 알림 후 종료 |

> `--tail`을 켜면 stdout/stderr를 파이프로 받아 중계합니다. tqdm 같은 진행바가
> 있는 학습은 기본값(`--tail 0`)이 출력이 가장 깨끗합니다.

---

## 알림에 찍히는 내용

시작할 때:

```
▶️ Job started: poster/train.py / student pku+kd
host: gpu-server-01
experiment: kd_pku_cgl
gpu: 1 (NVIDIA RTX A6000)
command: python -m poster.train --datasets pku --pseudo outputs/poster/pseudo/cgl_train.jsonl
start: 2026-07-09 01:10:22
```

끝날 때:

```
✅ Job finished: poster/train.py / student pku+kd
host: gpu-server-01
experiment: kd_pku_cgl
gpu: 1 (NVIDIA RTX A6000)
command: python -m poster.train --datasets pku --pseudo outputs/poster/pseudo/cgl_train.jsonl
elapsed: 3h 12m 40s
start: 2026-07-09 01:10:22
end:   2026-07-09 04:23:02
```

제목 줄(`Job finished:` 뒤)은 **코드에서 넘긴 라벨 그대로**입니다 — 기존 동작 그대로 유지.

- **experiment** — `experiment=` 인자 또는 `JOBNOTIFY_EXPERIMENT` 환경변수. 없으면 줄 자체가 생략됩니다.
- **gpu** — 이 프로세스가 실제로 쓰는 장치. `CUDA_VISIBLE_DEVICES`(도커면 `NVIDIA_VISIBLE_DEVICES`)로
  고른 id에 `nvidia-smi`의 장치 이름을 붙입니다:

  | 상황 | 출력 |
  |---|---|
  | `CUDA_VISIBLE_DEVICES=0` (3장 중 0번) | `0 (NVIDIA RTX A6000)` |
  | `CUDA_VISIBLE_DEVICES=0,2` | `0,2 (NVIDIA RTX A6000 x2)` |
  | 미설정 (3장 다 보임) | `0,1,2 (NVIDIA RTX A6000 x3)` |
  | `CUDA_VISIBLE_DEVICES=` (빈 값) | `none (CPU only, CUDA_VISIBLE_DEVICES=empty)` |
  | 도커 `--gpus '"device=1"'` | `0 (NVIDIA RTX A6000) [NVIDIA_VISIBLE_DEVICES=1]` |
  | `nvidia-smi` 없음 | `1` (id만) |

  이미 import된 torch가 CUDA를 초기화한 상태면 torch에서 이름을 읽습니다. **torch를 대신
  import하거나 CUDA를 초기화하지 않습니다.**
- **command** — `sys.argv` 복원. `python -m poster.train ...` 은 `train.py` 절대경로가 아니라
  입력한 그대로 보입니다. CLI로 감쌌으면 감싼 커맨드가 그대로 찍힙니다.

실패 시에는 ❌ 와 예외 타입·메시지·traceback 마지막 줄들이 함께 전송됩니다.
CLI로 감싼 경우엔 종료코드(`exit: 7`, `exit: killed by SIGTERM (-15)`)가 찍힙니다.

---

## 환경변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `JOBNOTIFY_TELEGRAM_TOKEN` | ✅ | BotFather 봇 토큰 |
| `JOBNOTIFY_TELEGRAM_CHAT_ID` | ✅ | 알림 받을 chat id |
| `JOBNOTIFY_JOB_NAME` | | 코드에서 job 이름을 안 넘길 때 쓰는 기본 라벨 |
| `JOBNOTIFY_DISABLE` | | `1`이면 모든 알림 끄기 |
| `JOBNOTIFY_EXPERIMENT` | | 알림에 찍을 실험 id (코드 수정 없이 `docker run -e` 로 주입 가능) |
| `JOBNOTIFY_GPU` | | GPU 자동 감지 대신 이 문자열을 사용 |
| `JOBNOTIFY_GPU_QUERY` | | `0`이면 `nvidia-smi` 호출 생략 |
| `JOBNOTIFY_CONTEXT` | | `0`이면 experiment/gpu/command 줄을 빼고 0.1.x 와 똑같은 메시지 |
| `JOBNOTIFY_NOTIFY_START` | | `0`이면 시작 알림 끄기 (기본은 켜짐) |

토큰/chat_id 중 하나라도 없으면 알림은 조용히 비활성화됩니다.

---

## 보안

- 실제 토큰은 **절대 커밋하지 마세요.** `.env`는 `.gitignore`에 등록되어 있고, 저장소에는
  placeholder만 담긴 `.env.example`만 올라갑니다.
- 소스코드는 자격증명을 오직 환경변수에서만 읽습니다 — 하드코딩된 비밀값이 없습니다.

---

## Docker 예시

```bash
docker run -d --name poster_kd --gpus '"device=1"' --shm-size=8g \
  -e JOBNOTIFY_TELEGRAM_TOKEN -e JOBNOTIFY_TELEGRAM_CHAT_ID \
  -e JOBNOTIFY_EXPERIMENT=kd_pku_cgl \
  -v /home/ci/bkk:/home/ci/bkk \
  myimage bash -c 'cd /home/ci/bkk/2026IEIE && \
    pip install "git+https://github.com/bogeoung/jobnotify.git" && \
    jobnotify -- python -m poster.train --datasets pku'
```

`--gpus '"device=1"'` 로 준 GPU는 컨테이너 안에서 index 0으로 보입니다. 알림의
`gpu:` 줄에는 컨테이너가 실제로 보는 장치와 `NVIDIA_VISIBLE_DEVICES` 값이 함께 찍히므로
어느 물리 GPU였는지 구분됩니다.

---

## 0.1.x 에서 올라올 때

공개 API·설치 방법·환경변수는 그대로입니다. **기존 코드는 한 줄도 고칠 필요가 없습니다.**
`notify_scope("...")` 를 그대로 두면 알림 제목은 넘긴 라벨 그대로이고, 달라지는 건:

- 시작 시점에 알림 1건이 추가로 옵니다 → 끄려면 `JOBNOTIFY_NOTIFY_START=0`
- 메시지에 experiment/gpu/command 줄이 붙습니다 → 빼려면 `JOBNOTIFY_CONTEXT=0`

새로 생긴 것: `jobnotify` CLI, `notify_scope(..., experiment=/gpu=/command=/notify_start=)`,
그리고 위 표의 `JOBNOTIFY_EXPERIMENT` 계열 환경변수.

---

## 확장 (다른 메신저 추가)

`src/jobnotify/backends.py`의 `Backend`를 상속해 새 백엔드(Discord/Slack 등)를 만들고
`build_backends()`에 등록하면 공개 API 변경 없이 채널을 추가할 수 있습니다.
