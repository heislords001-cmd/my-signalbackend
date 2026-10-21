# FX Desk scanner (backend)

The scanner watches the market all day, Monday to Friday, and sends signals. It only reads prices and never trades.
Pick ONE place to run it:

## A0. GitHub Actions (FREE: best for your testing month)
Costs nothing. GitHub runs `python worker.py --once` for you on a timer: every 5 minutes from 1pm to 5pm Nigeria time (Monday to Friday), and once an hour the rest of the day. That fits inside GitHub's free minutes for a private repository.
1. Put these files in a private GitHub repository. The folder `.github/workflows/scanner.yml` must be included. If a drag-and-drop upload skips it, use Add file > Create new file, type the name `.github/workflows/scanner.yml`, and paste the file's text.
2. In the repository: Settings > Secrets and variables > Actions > New repository secret. Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (and optionally `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
3. Open the Actions tab, pick "scanner", press **Run workflow**. The first run tests every strategy and takes a few minutes. Open the run to read its log.
4. On your website, Home, press **Start scanner**. Until you do, every run stops straight away.
Good to know: GitHub can start scheduled runs a few minutes late, and sometimes skips one, so a 5-minute signal can arrive late. If Yahoo ever blocks GitHub's servers, run the scanner on your own PC instead (section B).

## A. Railway (paid, about $5 a month)
1. Put these files in a new PRIVATE GitHub repository (on github.com: New repository, then "uploading an existing file", then drag in everything from this folder).
2. railway.com: sign in with GitHub, New Project, Deploy from GitHub repo, pick that repository.
3. Open the service's Variables tab and add:
   - `SUPABASE_URL` = your Supabase Project URL
   - `SUPABASE_SERVICE_KEY` = the service_role key (secret: only ever type it into Railway, never into the website or GitHub)
   - `FEED` = `yahoo`
   - optional: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (run `python telegram_setup.py` on your PC to find them)
4. It deploys and starts by itself (`railway.json` already says how). Open the Logs tab. You should see "Scanner started in ONLINE (Supabase) mode".
5. On your website, Home, press Start scanner.
Cost: Railway's docs list a one-time $5 trial credit, then a free plan with $1 of credit a month, then Hobby at $5 a month. An always-on scanner needs roughly the Hobby plan. A card may be required.

## A2. Render (works too, costs a little more)
1. Same private GitHub repository as above.
2. render.com: New, then **Background Worker** (NOT Web Service, which expects a website and sleeps when idle).
3. Pick the repository. Runtime Python. Build command `pip install -r requirements.txt`. Start command `python worker.py`. Instance type **Starter** (about $7 a month; the Free type sleeps and cannot keep a scanner running).
4. Environment variables: the same three as Railway (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FEED=yahoo`).
5. Create, then watch the Logs. Or use New > Blueprint, which reads `render.yaml` and asks you for the two secret values.

## A3. Render CRON JOB (runs every minute, usually the cheapest)
Use this instead of a Background Worker if you want Render to start the scanner by itself every minute.
1. render.com: New, then **Cron Job**. Pick the repository. Runtime Python.
2. Build command: `pip install -r requirements.txt`
3. **Command: `python worker.py --once`**   Schedule: `* * * * *`
4. Environment variables: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FEED=yahoo`, and `PYTHON_VERSION=3.11.9`.
5. The first run tests every strategy and takes a few minutes; later runs reuse the saved results and finish in seconds. A run only looks at the market in the 3 minutes after a candle closes, so most runs just report "alive" and stop. Duplicate signals are blocked by the database.
6. Do NOT use the plain command `python worker.py` in a cron job. That version never finishes.

## B. Your own PC, no website (LOCAL mode)
Leave SUPABASE_URL empty. Run `pip install -r requirements.txt`, then `python telegram_setup.py`, then double-click `start-scanner.bat`. Signals go to Telegram and to the `data` folder (`signals.csv` opens in Excel). The PC must stay on.

## C. A Windows or Linux server
See the steps further down.

---

Do this AFTER the database (supabase-setup.sql) and the website are set up.

## What is here
- `worker.py`: the SCANNER. It watches the market and sends signals to the website. It only reads prices and never trades.
- `test_*.py`: checks that the code works.
- `bot.py`, `engine.py`, `broker.py`: the trading bot. It needs MT5, so it runs on a Windows PC, not on this VPS. Members and you get it from the website (Profile > Bot access).

## Setup on a WINDOWS VPS (no MT5 needed to start)
1. Install Python 3.11 or newer from python.org. On the first screen, tick "Add python.exe to PATH".
2. Copy `fx-desk-backend.zip` to the VPS (copy and paste works through Remote Desktop). Right-click it, Extract All, for example into `C:\fxdesk`.
3. Open the `fx-desk-backend` folder, click the address bar at the top, type `cmd` and press Enter. A black window opens in that folder.
4. In the black window run: `pip install -r requirements.txt`
5. Make a copy of `.env.example` and name it `.env`. Open it with Notepad and fill in `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. Leave `FEED=yahoo`.
6. In the black window run: `python test_scanner.py` (it should end with "all scanner tests passed").
7. Double-click `start-scanner.bat`. A window opens and keeps the scanner running. Leave it open.
8. On the website: Home > Start scanner. The first start backtests everything and takes a few minutes.

### Keeping it running
- When you leave the VPS, close Remote Desktop with the X at the top (Disconnect). Never choose Sign out or Shut down, because that stops the scanner.
- To start it by itself after a reboot: open Task Scheduler > Create Basic Task > trigger "When the computer starts" > action "Start a program" > pick `start-scanner.bat`. Tick "Run whether user is logged on or not".

## Setup on a LINUX VPS (copy and paste these in your terminal, one block at a time)
Upload `fx-desk-backend.zip` to the VPS first (WinSCP, or the SFTP tab in Termius), into `/opt/fxdesk`. Then:

    sudo apt update && sudo apt install -y python3-venv unzip
    cd /opt/fxdesk && unzip -o fx-desk-backend.zip
    cd fx-desk-backend
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt

Create your settings file and fill it in (nano: arrows to move, Ctrl+O then Enter to save, Ctrl+X to exit):

    cp .env.example .env
    nano .env

Check everything works (it should end with "all scanner tests passed"):

    venv/bin/python test_scanner.py

Start it as a service that keeps running when you close the terminal, and restarts itself after a reboot:

    sudo cp fx-scanner.service /etc/systemd/system/
    sudo systemctl enable --now fx-scanner

Watch it run (Ctrl+C stops watching, NOT the scanner):

    sudo journalctl -u fx-scanner -f

Then on the website: Home > Start scanner. The first start backtests everything and takes a few minutes.

## Good to know
- The service key in `.env` is secret. It only lives on your VPS.
- Prices come from Yahoo Finance (free). They are close to your broker's, but not identical, so treat entries as approximate and use the distances to the stop and targets.
- Yahoo only gives about 2 months of 5-minute and 15-minute history and 2 years of 1-hour history. So fewer combinations pass the test at first, mostly 1-hour ones. That is the safety check being strict, not a fault.
- To update: upload the new zip, run `unzip -o`, then `sudo systemctl restart fx-scanner`.
