<p align="center">
  <img src="../images/06_text_logo_clear.png" alt="OpenLama" width="400">
  <br>
  <p align="center">
    <a href="https://ollama.com">Ollama</a> 기반의 완전 로컬 AI 에이전트 봇.<br>
    텔레그램 또는 터미널에서 도구 호출, 이미지 생성, 예약 작업, 커스텀 스킬을 사용하세요.<br>
    모든 데이터는 내 컴퓨터에서만 처리됩니다.
  </p>
  <p align="center">
    <a href="https://pypi.org/project/openlama/"><img src="https://img.shields.io/pypi/v/openlama" alt="PyPI"></a>
    <a href="https://pypi.org/project/openlama/"><img src="https://img.shields.io/pypi/pyversions/openlama" alt="Python"></a>
    <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  </p>
  <p align="center">
    <b><a href="../README.md">English</a></b>
  </p>
</p>

---

## 목차

- [왜 openlama인가?](#왜-openlama인가)
- [특징](#특징)
- [빠른 시작](#빠른-시작)
- [터미널 채팅 (TUI)](#터미널-채팅-tui)
- [텔레그램 봇](#텔레그램-봇)
- [내장 도구](#내장-도구-36개)
- [Google 연동](#google-연동)
- [Android (Termux) 설치 가이드](#android-termux-설치-가이드)
- [메모리 시스템](#메모리-시스템)
- [커스텀 스킬](#커스텀-스킬)
- [MCP 연동](#mcp-연동)
- [예약 작업](#예약-작업)
- [프롬프트 시스템](#프롬프트-시스템)
- [디렉토리 구조](#디렉토리-구조)
- [CLI 명령어 전체 목록](#cli-명령어-전체-목록)
- [설정](#설정)
- [추천 모델](#추천-모델)
- [시스템 요구 사항](#시스템-요구-사항)
- [기여하기](#기여하기)

---

## 왜 openlama인가?

대부분의 AI 비서는 데이터를 클라우드 서버로 보냅니다. openlama는 Ollama를 사용하여 로컬에서 완전히 실행되며, 도구 접근 권한이 있는 개인 AI 에이전트를 제공합니다. 데이터 유출 제로.

[Gemma 4](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/) 모델에 최적화되어 있으며, Ollama 호환 모델이라면 모두 사용 가능합니다.

---

## 특징

- **100% 로컬** — 클라우드 API 없음. 모든 처리가 내 하드웨어에서 실행.
- **듀얼 채널** — 텔레그램 봇 + 터미널 TUI. 대화 컨텍스트 공유.
- **36개 이상 내장 도구** — 웹 검색, 코드 실행, 파일 I/O, 이미지 생성, Git, Google Workspace (Gmail, Calendar, Drive, Docs, Sheets), Claude Code 에이전트 등.
- **커스텀 스킬** — 키워드에 자동 트리거되는 재사용 가능한 지침 세트.
- **MCP 지원** — [Model Context Protocol](https://modelcontextprotocol.io)로 외부 도구 서버 연결.
- **예약 작업** — 크론 기반 반복 작업을 AI가 실행.
- **메모리 시스템** — 2계층 구조: 장기 기억 (MEMORY.md) + 일별 에피소드 기억 (자동 저장).
- **멀티 프롬프트** — SOUL, USERS, MEMORY, SYSTEM 프롬프트를 분리하여 세밀하게 제어.
- **자동 업데이트** — `openlama update`로 openlama와 Ollama 동시 업데이트.
- **크로스 플랫폼** — macOS, Linux, Windows, **Android (Termux)**.
- **모바일 디바이스 제어** — Android에서 카메라, 문자, 위치, 센서 등을 Termux:API로 제어.
- **자가 복구** — `openlama doctor fix`로 문제 자동 진단 및 수리.

---

## 빠른 시작

### 1. 설치

```bash
# 권장
uv tool install openlama

# 또는 pip
pip install openlama
```

### 2. 초기 설정

```bash
openlama setup
```

대화형 마법사가 진행됩니다:

```
  ● Step 1/8 — Ollama
  ✓ Ollama is installed
  ✓ Ollama server running (v0.20.3)

  ● Step 2/8 — Models
  ? Select models to download:
    ✓ gemma4:e4b       9.6 GB  [recommended]
      qwen3:8b         5.2 GB  [light]
    ✓ gemma4:e2b                [installed]

  ● Step 3/8 — Channel
  ? Enter Telegram bot token (@BotFather): 1234567890:ABC...
  ✓ Connected: @your_bot_name

  ● Step 4/8 — Password
  ● Step 5/8 — Features
  ● Step 6/8 — Voice Recognition (STT)
  ● Step 7/8 — Obsidian Notes
  ● Step 8/8 — Google Integration (Optional)
  ? Enable Google integration? Yes
  ✓ Connected as user@gmail.com

  ╭─────────────────────────────────────────────╮
  │  ✅ Setup complete!                          │
  │                                              │
  │  Start:   openlama start                     │
  │  Chat:    openlama chat                      │
  │  Doctor:  openlama doctor                    │
  ╰─────────────────────────────────────────────╯
```

### 3. 실행

```bash
# 텔레그램 봇을 백그라운드로 실행
openlama start -d

# 터미널 채팅 열기 (텔레그램과 컨텍스트 공유)
openlama chat
```

### 4. 상태 진단

```bash
openlama doctor
```

```
  ✓  Data directory         /home/user/.config/openlama
  ✓  Database               7 tables
  ✓  Telegram bot token     Set (12345678...nqbw)
  ✓  Python dependencies    All critical packages available
  ✓  Boot service           systemd user service registered
  ✓  Ollama server          Connected (http://127.0.0.1:11434)
  ✓  Ollama version         v0.20.3 (latest)
  ✓  Ollama models          gemma4:e4b, gemma4:e2b

  17 passed · 1 warning(s)
```

---

## 터미널 채팅 (TUI)

```bash
openlama chat
```

```
──────────────────────────── openlama ─────────────────────────────
  model: gemma4:e4b | ctx: 12% (8 turns) | telegram: @your_bot
  Type / for commands, /quit to exit.

You: 서울 날씨 알려줘

╭──────────────────────────── AI ─────────────────────────────────╮
│                                                                  │
│  검색해보겠습니다.                                                 │
│                                                                  │
│  현재 서울 기온은 18°C, 구름 약간 끼어 있습니다.                     │
│  습도 45%, 북서풍 약풍입니다.                                      │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
  📊 ██░░░░░░░░░░░░░░░░░░ 12.3% (2,841/32,768 tokens)  |  turns: 9
```

### 채팅 명령어

`/` 를 입력하면 모든 명령어를 확인할 수 있습니다:

```
  Chat
    /help             명령어 목록
    /clear            대화 컨텍스트 초기화
    /status           세션 및 컨텍스트 정보
    /compress         대화 컨텍스트 압축
    /session          세션 조회/연장
    /export           대화 내보내기
    /profile          프로필 재설정
    /quit             채팅 종료

  Model
    /model            현재 모델 변경
    /models           사용 가능한 모델 목록 (기능 뱃지)
    /pull             새 모델 다운로드
    /rm               모델 삭제

  Settings
    /settings         인터랙티브 모델 설정
    /set <p> <v>      파라미터 변경
    /think            추론 모드 토글
    /systemprompt     프롬프트 파일 보기/편집

  System
    /ollama           Ollama 서버 상태
    /skills           스킬 목록
    /mcp              MCP 서버 상태
    /cron             예약 작업 관리
    /tools            등록된 도구 목록
```

---

## 텔레그램 봇

`openlama start` 후 텔레그램에서 봇에 메시지를 보내세요:

1. **로그인** — 메시지 전송 → 관리자 비밀번호 입력
2. **프로필 설정** — 언어 선택, 자기소개, 에이전트 정체성 설정
3. **채팅** — 대화 시작. 봇이 자동으로 도구를 사용합니다.

### 텔레그램 기능

- 설정, 모델 선택을 위한 인라인 키보드 메뉴
- 실시간 스트리밍 응답
- 이미지/문서/오디오/비디오/ZIP 파일 분석
- 음성 메시지 텍스트 변환 (STT, faster-whisper)
- 토큰 사용량 표시 (Ollama 실제 토큰)
- 인라인 버튼으로 프롬프트 파일 편집

---

## 내장 도구 (36+개)

| 도구 | 설명 |
|------|------|
| `web_search` | DuckDuckGo 웹 검색 |
| `url_fetch` | URL에서 텍스트 추출 |
| `calculator` | 수학 연산 |
| `code_execute` | Python, Node.js, Shell 코드 실행 |
| `shell_command` | 시스템 명령 실행 |
| `file_read` | 파일 읽기 / 디렉토리 목록 |
| `file_write` | 파일 쓰기 / 추가 |
| `git` | Git 작업 (status, log, diff, commit) |
| `process_manager` | 프로세스 관리, 시스템 상태 |
| `tmux` | tmux 터미널 멀티플렉서 제어 |
| `image_generate` | ComfyUI 텍스트→이미지 |
| `image_edit` | ComfyUI 이미지 편집 |
| `memory` | 2계층 기억: 장기 기억 + 일별 에피소드 |
| `skill_creator` | 커스텀 스킬 생성/관리/설치 |
| `mcp_manager` | MCP 서버 설치/관리 |
| `cron_manager` | 예약 작업 등록/관리 |
| `get_datetime` | 현재 날짜/시간 |
| `self_update` | openlama 업데이트 확인/설치 |
| `whisper` | 오디오/음성 텍스트 변환 (STT, 선택) |
| `obsidian` | 옵시디언 노트 읽기/쓰기/검색 (선택) |
| `code_agent` | Claude Code CLI 에이전트 — 복잡한 코딩 작업 수행 |
| `termux_device` | Android 디바이스 제어 — Termux:API (Android 전용) |

<details>
<summary><b>Google Workspace 도구 (14개 도구, 164개 액션)</b></summary>

| 도구 | 액션 |
|------|------|
| `google_auth` | OAuth 인증, 상태 확인, 연동 해제 |
| `google_gmail` | 검색, 발송, 답장, 라벨, 임시저장, 필터, 자동응답, 전달, 위임 (37개) |
| `google_calendar` | 일정 조회/생성/수정, 참석 응답, 빈 시간, 충돌, 집중시간, 부재중 (15개) |
| `google_drive` | 파일 목록/검색/업로드/다운로드/공유, 댓글, 공유 드라이브 (20개) |
| `google_docs` | 읽기, 생성, 내보내기, 쓰기, 찾기/바꾸기, 댓글 (16개) |
| `google_sheets` | 범위 읽기/쓰기, 생성, 서식, 병합, 고정, 명명 범위, 탭 (22개) |
| `google_slides` | 생성, 내보내기, 슬라이드 읽기, 발표자 노트 (9개) |
| `google_contacts` | 연락처 목록/검색/생성/수정/삭제 (6개) |
| `google_tasks` | 작업 목록, 추가/완료/삭제 (9개) |
| `google_forms` | 설문 생성, 질문 추가, 응답 조회 (8개) |
| `google_keep` | 메모 목록/생성/검색/삭제 (6개) |
| `google_people` | 프로필, 디렉토리 검색, 관계 (4개) |
| `google_chat` | 스페이스, 메시지, DM, 리액션 (8개, Workspace) |
| `google_appscript` | 스크립트 조회/생성/실행 (4개) |

</details>

AI는 어떤 언어로 요청해도 도구를 사용합니다:

> "서버 상태 확인해줘" → `shell_command`
> "search for latest AI news" → `web_search`
> "john에게 회의 관련 메일 보내줘" → `google_gmail`
> "내일 일정 알려줘" → `google_calendar`
> "배터리 확인해줘" → `termux_device` (Android)

---

## Google 연동

Google 계정을 연동하여 Gmail, Calendar, Drive, Docs, Sheets 등을 로컬 AI 에이전트에서 관리합니다.

### 설정 방법

**1. OAuth 인증 정보 생성** — [Google Cloud Console](https://console.cloud.google.com/):
   - 프로젝트 생성 → API 활성화 (Gmail, Calendar, Drive, Docs, Sheets 등)
   - OAuth 클라이언트 ID 생성 → **데스크톱 앱** 선택 → `credentials.json` 다운로드

**2. 설정** — 초기 설정 마법사 또는 CLI:

```bash
# 초기 설정 시 (Step 8)
openlama setup

# 또는 언제든
openlama google auth
```

**3. 확인:**

```bash
openlama google status
```

```
  Google integration: enabled
  Credentials: ✓ stored
  Token: ✓ stored
  Account: user@gmail.com
  Status: ✓ valid
```

### CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `openlama google auth` | Google 인증 (브라우저 열림) |
| `openlama google status` | 연동 상태 확인 |
| `openlama google revoke` | Google 계정 연동 해제 |

> **참고:** 최초 인증 시 브라우저가 필요합니다 (로컬 GUI). 이후에는 토큰이 자동 갱신됩니다. 인증 정보는 암호화되어 로컬 데이터베이스에 저장됩니다.

---

## Android (Termux) 설치 가이드

openlama는 [Termux](https://termux.dev)를 통해 Android에서 실행됩니다. 두 가지 모드를 지원합니다.

### 모드 1: 원격 추론 (권장)

봇은 휴대폰에서 실행하고, 추론은 데스크톱/서버의 GPU에서 처리합니다.

#### 사전 준비

- **Termux** — [F-Droid](https://f-droid.org/packages/com.termux/) 또는 [GitHub Releases](https://github.com/termux/termux-app/releases)에서 설치 (권장). [Google Play 버전](https://play.google.com/store/apps/details?id=com.termux)은 기본 봇 실행은 가능하지만 플러그인 미지원 (아래 참고).
- [Termux:API](https://f-droid.org/packages/com.termux.api/) — 디바이스 전체 제어용 (카메라, 문자, GPS, 센서). **F-Droid/GitHub 전용.**
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) — 부팅 시 자동 시작. **F-Droid/GitHub 전용.**
- Ollama가 실행 중인 데스크톱/서버 (네트워크 접근 가능)

> **F-Droid vs Play Store vs GitHub:**
>
> | | F-Droid / GitHub | Google Play |
> |---|---|---|
> | 봇 데몬 + 원격 Ollama | ✅ | ✅ |
> | Termux:API 플러그인 (35개 디바이스 액션) | ✅ | ❌ (일부 내장) |
> | Termux:Boot (부팅 자동시작) | ✅ | ❌ |
> | 최신 기능 (v0.118+) | ✅ | ❌ (v0.108 수준) |
>
> 모든 Termux APK는 **같은 출처**에서 설치해야 합니다 (F-Droid, GitHub, Play Store 중 택일). 출처를 섞으면 서명키 불일치로 설치 실패합니다. F-Droid와 GitHub APK는 동일한 서명키를 사용하므로 호환됩니다.
>
> **Google Play Protect**가 F-Droid/GitHub APK 설치를 차단할 수 있습니다. 경고를 무시하거나 설치 중 Play Protect를 일시 비활성화하세요.

#### 설치 과정

```bash
# 1. Termux 패키지 업데이트
pkg update && pkg upgrade -y

# 2. Python 및 Termux:API 브릿지 설치
pkg install python termux-api -y

# 3. openlama 설치
pip install openlama

# 4. 초기 설정 마법사 실행
openlama setup
#   Step 1: "Remote" 선택 → 서버 URL 입력 (예: http://192.168.1.100:11434)
#   Step 2: 원격 서버의 모델 선택
#   Step 3: 텔레그램 봇 토큰 입력
#   Step 4: 비밀번호 설정

# 5. 봇 시작
openlama start -d

# 6. (선택) 부팅 시 자동 시작 등록 (F-Droid/GitHub 전용)
openlama start --install-service
```

> **참고:** 원격 Ollama 서버에서 `OLLAMA_HOST=0.0.0.0 ollama serve`로 실행해야 네트워크 연결을 받을 수 있습니다.

### 모드 2: 온디바이스 추론

모든 것을 휴대폰에서 실행합니다 (RAM 8GB 이상 권장).

```bash
# Termux User Repository를 통해 Ollama 설치
pkg install tur-repo -y
pkg install ollama python termux-api -y

# openlama 설치 및 설정
pip install openlama
openlama setup    # "Local" 선택 → 모델 다운로드 (~3-7 GB)

openlama start -d
```

### Android 디바이스 제어

Android에서 실행 시, `termux_device` 도구로 AI가 휴대폰을 제어할 수 있습니다 ([Termux:API](https://f-droid.org/packages/com.termux.api/) F-Droid/GitHub 설치 필요):

| 카테고리 | 기능 |
|----------|------|
| **전화** | call, sms_send, sms_list, call_log, contacts |
| **카메라** | camera_photo (전면/후면), camera_info |
| **오디오** | mic_record, media_play, tts_speak, volume_get/set |
| **센서** | location, battery, sensor_list/read |
| **시스템** | brightness, torch, clipboard, wifi_info/scan |
| **알림** | notification, toast, vibrate |
| **앱** | app_launch, app_list, share, download |

안전 규칙이 적용됩니다:
- 전화 및 문자는 **반드시 사용자 확인 후** 실행
- 위치 정보는 **동의 없이 절대 공유하지 않음**

### 모바일 추천 모델

| 모델 | 크기 | 비고 |
|------|------|------|
| **`gemma4:e2b`** | **7.2 GB** | **모바일 최적** — 2.3B 유효 파라미터 |
| `gemma3:4b` | 3.3 GB | 균형 잡힌 성능 |
| `phi4-mini` | 2.5 GB | 경량 |
| `gemma3:1b` | 0.8 GB | 초경량, 최소 하드웨어 |

### Android에서 openlama 유지하기

openlama는 화면이 꺼져도 CPU가 동작하도록 **wake lock**을 자동 획득합니다. 하지만 최신 Android에서는 wake lock만으로 부족하므로 추가 설정이 필요합니다:

**필수 (모든 기기):**
- 배터리 최적화 해제: 설정 → 앱 → Termux → 배터리 → **제한 없음**

**필수 (Android 12 이상):**
- 팬텀 프로세스 킬러 비활성화: 설정 → 개발자 옵션 → **자식 프로세스 제한 비활성화**
- 개발자 옵션이 없다면: 설정 → 휴대전화 정보 → 빌드 번호 7회 탭

**제조사별 ([dontkillmyapp.com](https://dontkillmyapp.com) 참고):**
- **삼성**: 설정 → 배터리 → 백그라운드 사용 제한 → 절전 제외 앱 → Termux 추가
- **샤오미/MIUI**: 설정 → 배터리 → 앱 배터리 절약 → Termux → 제한 없음; 자동시작도 허용
- **화웨이/EMUI**: 설정 → 배터리 → 앱 실행 → Termux → 수동 관리 (모두 허용)
- **원플러스**: 설정 → 배터리 → 배터리 최적화 → Termux → 최적화 안 함

---

## 메모리 시스템

openlama는 2계층 메모리 아키텍처를 사용합니다:

### 장기 기억 (MEMORY.md)
- 중요한 사실, 사용자 선호, 핵심 결정 사항을 저장합니다.
- `memory` 도구로 관리 (save/list/search/delete).
- 키워드 검색으로 접근 — 로컬 LLM의 컨텍스트를 절약하기 위해 **시스템 프롬프트에 로드되지 않습니다**.

### 일별 에피소드 기억 (memories/YYYY-MM-DD.md)
- 컨텍스트 압축, 대화 초기화, 일일 플러시 시 자동 저장됩니다.
- `memory` 도구로 날짜와 키워드로 검색 (list_dates/read_daily/search_daily).
- AI가 과거 대화를 회상할 수 있습니다: _"어제 뭐 얘기했지?"_

---

## 커스텀 스킬

키워드에 자동으로 활성화되는 스킬 생성:

### CLI로 생성

```bash
openlama skill create
```

### 대화로 생성

> "코드 리뷰를 해달라고 하면 트리거되는 스킬을 만들어줘"

### 스킬 파일 형식

`~/.config/openlama/skills/<이름>/SKILL.md`:

```markdown
---
name: code-reviewer
description: "코드 리뷰 요청 시 활성화"
trigger: "리뷰, 코드 리뷰, 검토해줘"
---

## 규칙
1. 사용자가 지정한 파일을 읽는다
2. 버그, 보안 이슈, 성능 문제를 확인한다
3. 코드 예시와 함께 개선점을 제안한다
```

---

## MCP 연동

[Model Context Protocol](https://modelcontextprotocol.io)로 외부 도구 연결:

```bash
openlama mcp add github npx -y @github/github-mcp
openlama mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /home
openlama mcp list
openlama mcp remove github
```

---

## 예약 작업

자연어로 예약 — AI가 크론 표현식으로 변환:

> "매 시간 디스크 사용량 확인해줘" → `0 */1 * * *`
> "매일 아침 9시에 기술 뉴스 요약해줘" → `0 9 * * *`
> "5분마다 서버 상태 모니터링해줘" → `*/5 * * * *`

실행마다 AI가 도구를 사용하여 1회성으로 작업을 수행하고, 결과를 채팅으로 전송합니다.

```bash
openlama cron list       # 작업 목록
openlama cron delete 1   # 작업 삭제
```

---

## 프롬프트 시스템

| 파일 | 용도 | 편집 가능 |
|------|------|----------|
| `SYSTEM.md` | 도구, 규칙, 스킬 목록 | 매 요청 시 자동 생성 |
| `SOUL.md` | 에이전트 정체성과 성격 | `/systemprompt`로 편집 |
| `USERS.md` | 사용자 프로필과 언어 | `/systemprompt`로 편집 |
| `MEMORY.md` | 장기 기억 항목 | `memory` 도구로 관리 (프롬프트에 비포함) |

모든 파일은 `~/.config/openlama/prompts/`에 있으며:
- **텔레그램**: `/systemprompt` → 파일 선택 → 내용 확인 → 수정 후 전송
- **CLI**: `/systemprompt` → `$EDITOR` (nano/vim/code)로 직접 편집

---

## 디렉토리 구조

```
~/.config/openlama/
├── openlama.db              # SQLite (설정, 사용자, 컨텍스트, 크론)
├── openlama.pid             # 데몬 PID 파일
├── openlama.log             # 데몬 로그
├── mcp.json                 # MCP 서버 설정
├── prompts/
│   ├── SYSTEM.md            # 자동 생성 시스템 프롬프트
│   ├── SOUL.md              # 에이전트 정체성
│   ├── USERS.md             # 사용자 프로필
│   └── MEMORY.md            # 장기 기억 (도구로만 접근)
├── memories/
│   └── YYYY-MM-DD.md        # 일별 에피소드 기억
├── skills/
│   └── <이름>/SKILL.md       # 커스텀 스킬
└── workflows/
    ├── txt2img_default.json  # ComfyUI 텍스트→이미지
    └── img2img_default.json  # ComfyUI 이미지→이미지
```

---

## CLI 명령어 전체 목록

<details>
<summary><b>전체 명령어 목록</b></summary>

| 명령어 | 설명 |
|--------|------|
| `openlama setup` | 대화형 초기 설정 |
| `openlama start` | 텔레그램 봇 실행 (포그라운드) |
| `openlama start -d` | 백그라운드 데몬 실행 |
| `openlama start --install-service` | OS 서비스 등록 (부팅 시 자동 시작) |
| `openlama start --uninstall-service` | OS 서비스 해제 |
| `openlama stop` | 데몬 중지 |
| `openlama restart` | 데몬 재시작 |
| `openlama chat` | 터미널 채팅 TUI |
| `openlama status` | 연결 및 프로세스 상태 |
| `openlama doctor` | 진단 실행 |
| `openlama doctor fix` | 자동 수정 |
| `openlama update` | openlama + Ollama 업데이트 |
| `openlama config list` | 설정 목록 |
| `openlama config get <key>` | 설정 값 조회 |
| `openlama config set <key> <value>` | 설정 변경 (데몬 자동 재시작) |
| `openlama config reset` | 설정 초기화 |
| `openlama config stt` | 음성인식(STT) 상태 확인 |
| `openlama config stt install` | faster-whisper 설치 |
| `openlama config stt enable/disable` | STT 활성화/비활성화 |
| `openlama config obsidian` | 옵시디언 연동 상태 확인 |
| `openlama config obsidian install` | obsidian-cli 설치 |
| `openlama config obsidian vault <name>` | 옵시디언 볼트 설정 |
| `openlama config obsidian disable` | 옵시디언 연동 비활성화 |
| `openlama skill list` | 스킬 목록 |
| `openlama skill create` | 스킬 생성 |
| `openlama skill delete <name>` | 스킬 삭제 |
| `openlama mcp list` | MCP 서버 목록 |
| `openlama mcp add <name> <cmd> [args]` | MCP 서버 추가 |
| `openlama mcp remove <name>` | MCP 서버 제거 |
| `openlama google auth` | Google 인증 (브라우저 열림) |
| `openlama google status` | Google 연동 상태 |
| `openlama google revoke` | Google 계정 연동 해제 |
| `openlama tool list` | 등록된 도구 목록 |
| `openlama cron list` | 예약 작업 목록 |
| `openlama cron delete <id>` | 예약 작업 삭제 |
| `openlama logs` | 데몬 로그 |
| `openlama --version` | 버전 확인 |

</details>

---

## 추천 모델

### 데스크톱 / 서버

| 모델 | 크기 | 용도 |
|------|------|------|
| **`gemma4:e4b`** | **9.6 GB** | **종합 최고 — 기본 추천** |
| `gemma3:4b` | 3.3 GB | 빠른 응답, 낮은 메모리 |
| `qwen3.5:4b` | 3.4 GB | 다국어 지원 우수 |
| `qwen3:8b` | 5.2 GB | 강한 추론 능력 |
| `deepseek-r1:8b` | 5.2 GB | 코딩 작업 |
| `gemma3:1b` | 0.8 GB | 초경량, 최소 하드웨어 |

### 모바일 (Android)

| 모델 | 크기 | 용도 |
|------|------|------|
| **`gemma4:e2b`** | **7.2 GB** | **모바일 최적 — 2.3B 유효 파라미터** |
| `gemma3:4b` | 3.3 GB | 균형 잡힌 성능 |
| `phi4-mini` | 2.5 GB | 경량 |
| `gemma3:1b` | 0.8 GB | 초경량, 1GB RAM 디바이스 |

---

## 시스템 요구 사항

### 데스크톱 / 서버

| 항목 | 최소 | 권장 |
|------|------|------|
| Python | 3.11+ | 3.13+ |
| RAM | 4 GB | 8 GB+ |
| 디스크 | 5 GB | 20 GB+ (모델 포함) |
| OS | macOS / Linux / Windows | macOS (Apple Silicon) |
| [Ollama](https://ollama.com) | 필수 | 최신 버전 |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 선택 | 이미지 생성용 |

### Android (Termux)

| 항목 | 최소 | 권장 |
|------|------|------|
| Android | 7+ | 12+ |
| RAM | 4 GB (원격 모드) | 8 GB+ (온디바이스) |
| 디스크 | 500 MB (원격) | 8 GB+ (온디바이스) |
| [Termux](https://f-droid.org/packages/com.termux/) | 필수 | [F-Droid](https://f-droid.org/packages/com.termux/) 또는 [GitHub](https://github.com/termux/termux-app/releases) |
| [Termux:API](https://f-droid.org/packages/com.termux.api/) | 권장 | 디바이스 제어용 (F-Droid/GitHub 전용) |
| [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) | 선택 | 자동 시작용 (F-Droid/GitHub 전용) |

---

## 설정

모든 설정은 SQLite에 저장됩니다 (`~/.config/openlama/openlama.db`).

데이터 디렉토리 변경:

```bash
export OPENLAMA_DATA_DIR=/custom/path
```

주요 설정:

| 키 | 기본값 | 설명 |
|----|--------|------|
| `telegram_bot_token` | — | 텔레그램 봇 API 토큰 |
| `default_model` | — | 기본 Ollama 모델 |
| `ollama_base` | `http://127.0.0.1:11434` | Ollama API URL |
| `comfy_enabled` | `false` | ComfyUI 연동 활성화 |
| `comfy_base` | `http://127.0.0.1:8184` | ComfyUI API URL |
| `tool_sandbox_path` | `~/sandbox` | 코드 실행 샌드박스 |
| `obsidian_vault` | — | 옵시디언 볼트 이름 (설정 시 도구 활성화) |
| `stt_enabled` | `auto` | 음성 인식: `true`/`false`/`auto` |
| `google_enabled` | `false` | Google 연동: `true`/`false` |

---

## 기여하기

기여를 환영합니다! 다음 순서로 진행해주세요:

1. 저장소 Fork
2. 기능 브랜치 생성 (`git checkout -b feature/amazing-feature`)
3. 변경 사항 작성
4. 테스트 실행 (`pytest`)
5. 커밋 (`git commit -m 'feat: add amazing feature'`)
6. 푸시 (`git push origin feature/amazing-feature`)
7. Pull Request 생성

### 개발 환경 설정

```bash
git clone https://github.com/OpenLamaAI/openlama.git
cd openlama
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
openlama setup
```

---

## 로드맵

- [ ] 웹 UI 채널
- [ ] Discord 채널
- [ ] iOS Shortcuts 연동
- [ ] 멀티유저 (분리된 컨텍스트)
- [ ] RAG (로컬 문서 검색 증강 생성)
- [ ] 음성 입출력
- [ ] 플러그인 마켓플레이스

---

## 라이선스

[MIT](../LICENSE)

---

<p align="center">
  Ollama, python-telegram-bot, Rich, Click으로 제작.<br>
  <sub>나의 AI, 나의 하드웨어, 나의 데이터.</sub>
</p>
