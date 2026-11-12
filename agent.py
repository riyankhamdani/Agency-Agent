import json
import os
import random
import sys
import time
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import requests
import telebot
from google import genai
from google.genai import types

# Environment Credentials
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_NEWS_FILE = os.path.join(BASE_DIR, "seen_news.json")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


def normalize_url(raw_url: str) -> str:
    """Membersihkan URL dari query parameters dan trailing slash."""
    try:
        parsed = urlparse(raw_url)
        return urlunparse(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", "")
        )
    except Exception:
        return raw_url.strip().rstrip("/")


def load_seen_news() -> set:
    """Membaca riwayat URL berita. Menginisialisasi file jika belum ada."""
    if not os.path.exists(SEEN_NEWS_FILE):
        try:
            with open(SEEN_NEWS_FILE, "w") as f:
                json.dump([], f)
            print(f"📄 File {SEEN_NEWS_FILE} berhasil diinisialisasi otomatis.")
        except Exception as e:
            print(f"⚠️ Gagal inisialisasi awal {SEEN_NEWS_FILE}: {e}")
        return set()

    try:
        with open(SEEN_NEWS_FILE, "r") as f:
            return set(json.load(f))
    except Exception as e:
        print(f"⚠️ Gagal membaca {SEEN_NEWS_FILE}: {e}")
        return set()


def save_seen_news(seen_news: set):
    """Menyimpan riwayat URL ke file JSON."""
    try:
        with open(SEEN_NEWS_FILE, "w") as f:
            json.dump(list(seen_news), f, indent=2)
        print(f"💾 Berhasil menyimpan {len(seen_news)} URL ke {SEEN_NEWS_FILE}")
    except Exception as e:
        print(f"⚠️ Gagal menyimpan {SEEN_NEWS_FILE}: {e}")


def search_tavily(query: str, seen_urls: set, domains: list = None, topic: str = "general"):
    """Karyawan 1 (Scout): Menyisir intel teknis dan bounty/hackathon."""
    if not TAVILY_API_KEY:
        print("⚠️ Warning: TAVILY_API_KEY tidak ditemukan.")
        return []

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "topic": topic,
        "days": 3,
        "max_results": 7,
        "search_depth": "advanced",
    }
    if domains:
        payload["include_domains"] = domains

    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            results = response.json().get("results", [])
            valid_articles = []
            for r in results:
                raw_link = r.get("url", "")
                clean_link = normalize_url(raw_link)

                if clean_link in seen_urls or raw_link in seen_urls:
                    continue

                valid_articles.append({
                    "title": r.get("title", "No Title"),
                    "url": raw_link,
                    "clean_url": clean_link,
                    "snippet": r.get("content", "")[:600],
                })

            return valid_articles[:3]
        else:
            print(f"❌ Tavily Error status code: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Error fetching from Tavily: {e}")
        return []


def generate_with_fallback(client, prompt: str, temperature: float = 0.3, retries_per_model: int = 3, initial_delay: int = 5) -> str:
    """Memanggil Gemini API secara dinamis dengan fallback model aktif di akun."""
    candidate_models = []

    try:
        active_models = [m.name.replace("models/", "") for m in client.models.list()]
        preferred = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-1.5-pro",
        ]
        for pref in preferred:
            if pref in active_models:
                candidate_models.append(pref)
        for m in active_models:
            if "gemini" in m and "embedding" not in m and m not in candidate_models:
                candidate_models.append(m)
    except Exception as e:
        print(f"⚠️ Gagal membaca model dinamis: {e}. Menggunakan fallback default.")

    if not candidate_models:
        candidate_models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-2.5-pro",
        ]

    config = types.GenerateContentConfig(
        temperature=temperature,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for model_name in candidate_models:
        print(f"🔄 Mencoba generate dengan model: {model_name}")
        for attempt in range(1, retries_per_model + 1):
            try:
                response = client.models.generate_content(
                    model=model_name, contents=prompt, config=config
                )
                if response.text:
                    print(f"✅ Sukses generate menggunakan model: {model_name}")
                    return response.text
            except Exception as e:
                err_msg = str(e)
                print(f"⚠️ [{model_name}] Percobaan {attempt}/{retries_per_model} Gagal: {err_msg[:120]}")

                if any(k in err_msg.lower() for k in ["not found", "404", "deprecated", "limit: 0", "unsupported"]):
                    print(f"⏩ Model {model_name} tidak didukung akun ini. Lewati...")
                    break

                delay = (initial_delay * attempt) + random.uniform(1.0, 3.0)
                time.sleep(delay)

    raise Exception("Gagal mendapatkan respons dari seluruh kandidat model Gemini.")


def agent_architect(client, digest_data: dict) -> str:
    """
    Karyawan 2 (Solutions & Content Architect):
    Mengubah berita mentah menjadi aset siap pakai (Draf Postingan Authority + Blueprint Eksekusi Bounty).
    """
    prompt = f"""
You are a Senior Cloud/SRE Solutions Architect and Ghostwriter working for Riyan (a Cloud & DevOps Engineer experienced in Kubernetes, Terraform, CI/CD, and AI infra).
Your job is NOT just to summarize news, but to turn raw intelligence into READY-TO-USE MONEY & AUTHORITY ASSETS so Riyan doesn't have to think from scratch.

RAW DATA:
{json.dumps(digest_data, indent=2)}

Instructions:
1. Analyze the items in OUTAGES, CLOUD_AI_INFRA, and HACKATHONS_BOUNTIES.
2. Pick ONLY the highest-impact technical incident/release and the best ACTIVE/UPCOMING hackathon or paid bounty (discard any ended/finished events).
3. Produce TWO actionable deliverables in clean, sharp formatting (Indonesian for explanations, punchy English for the LinkedIn/X post draft so it reaches global clients/recruiters):

Deliverable A — 📢 READY-TO-POST LINKEDIN/X DRAFT (Inbound Client Magnet):
- Pick the single most interesting outage, CVE, or infra trend from the data.
- Write a short, sharp, non-robotic post (max 120 words) from Riyan's perspective sharing 1 architectural takeaway or prevention tip. No cringe hashtags, no "I am excited to announce". Ready to copy-paste.

Deliverable B — 💰 ACTIONABLE BOUNTY / HACKATHON BLUEPRINT:
- Pick the best active bounty/hackathon with real cash/grant rewards. (If none are active/valid, write "Tidak ada bounty aktif yang layak hari ini.")
- Provide: Name, Prize/Reward, Direct URL, and a 3-bullet "Quick MVP Blueprint" on how Riyan can build/submit it fast using Python/K8s/AI.

Deliverable C — ⚡ QUICK INTEL RADAR (Max 2-3 bullets):
- Brief 1-line summary + URL of the remaining notable tech links just for awareness.

Output ONLY the formatted Telegram message using this exact template:

🤖 **AI AGENCY BRIEFING (READY TO EXECUTE)**
====================================

📢 **DRAF POSTINGAN LINKEDIN / X (TINGGAL COPAS)**
"[Isi draf postingan bahasa Inggris yang tajam & natural]"
🔗 Sumber inspirasi: [URL]

💰 **TARGET BOUNTY / HACKATHON & BLUEPRINT**
- **[Nama Bounty / Hackathon]** (Hadiah: [Nominal])
  🛠️ **Blueprint Eksekusi:**
  1. [Langkah teknis 1]
  2. [Langkah teknis 2]
  3. [Langkah teknis 3]
  🔗 Daftar/Eksekusi: [URL]

⚡ **RADAR TEKNIS SINGKAT**
- **[Judul]** — [1 kalimat intisari] ([URL])
"""
    return generate_with_fallback(client, prompt, temperature=0.4)


def agent_quality_control(client, raw_data: dict, draft_briefing: str) -> dict:
    """
    Karyawan 3 (QC Gatekeeper):
    Menilai apakah briefing hari ini cukup berbobot untuk dikirim ke Telegram bos (Riyan).
    """
    prompt = f"""
You are a strict Quality Control Editor for Riyan's AI Agency.
Review the generated briefing below against the raw search data:

GENERATED BRIEFING:
{draft_briefing}

Scoring Rules (1-10):
- Give 8-10 if: There is a genuinely useful technical insight/post draft AND/OR a valid active paid bounty/hackathon with clear steps.
- Give 1-6 if: All items are generic fluff, outdated/finished hackathons, hallucinated URLs not present in raw data, or zero actionable value.

Output STRICTLY valid JSON without markdown blocks:
{{"score": 8, "reason": "Alasan singkat dalam bahasa Indonesia", "approved": true}}
"""
    try:
        raw_res = generate_with_fallback(client, prompt, temperature=0.1)
        clean_json = raw_res.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Warning QC parse gagal ({e}), meloloskan draf secara default.")
        return {"score": 7, "reason": "Auto-approved (QC JSON fallback)", "approved": True}


def get_news_digest(seen_urls: set):
    """Pipeline Kantor AI: Scout -> Architect -> QC Gatekeeper."""
    today_str = datetime.now().strftime("%B %Y")

    search_configs = {
        "OUTAGES": {
            "query": f'("post-mortem" OR "outage analysis" OR "incident retrospective") ("Kubernetes" OR "AWS" OR "Cloudflare" OR "cloud") {today_str}',
            "domains": None,
            "topic": "news",
        },
        "CLOUD_AI_INFRA": {
            "query": f'("Kubernetes security" OR "CVE" OR "vLLM" OR "AI infrastructure" OR "Terraform") ("release" OR "architecture") {today_str}',
            "domains": None,
            "topic": "news",
        },
        "HACKATHONS_BOUNTIES": {
            "query": (
                '("AI hackathon" OR "cloud challenge" OR "bounty" OR "developer grant") '
                '("prize pool" OR "cash prize" OR "reward") '
                '("register" OR "registration open" OR "LIVE" OR "upcoming") '
                '-finished -ended'
            ),
            "domains": [
                "devpost.com",
                "dorahacks.io",
                "lablab.ai",
                "algora.io",
                "polar.sh",
                "taikai.network",
            ],
            "topic": "general",
        },
    }

    # 1. Karyawan 1 (Scout) bekerja
    digest_data = {}
    for cat, cfg in search_configs.items():
        digest_data[cat] = search_tavily(
            cfg["query"], seen_urls, domains=cfg["domains"], topic=cfg["topic"]
        )

    new_urls = [
        item["clean_url"]
        for cat in digest_data.values()
        for item in cat
    ]

    if not new_urls:
        print("ℹ️ Tidak ada update baru hari ini.")
        return None, []

    if not GEMINI_API_KEY:
        return "❌ Error: GEMINI_API_KEY belum dikonfigurasi.", []

    client = genai.Client(api_key=GEMINI_API_KEY)

    # 2. Karyawan 2 (Architect) meracik draf konten & blueprint bounty
    print("🧠 Karyawan 2 (Architect) sedang menyusun draf konten & blueprint...")
    briefing_text = agent_architect(client, digest_data)

    # 3. Karyawan 3 (QC) menyaring kualitas sebelum ganggu HP lu
    print("🕵️ Karyawan 3 (QC) sedang memeriksa kualitas hasil...")
    qc_result = agent_quality_control(client, digest_data, briefing_text)
    score = qc_result.get("score", 0)
    reason = qc_result.get("reason", "-")
    print(f"📊 Hasil QC: Skor {score}/10 | Alasan: {reason}")

    if score < 7 or not qc_result.get("approved", False):
        print("🛑 Draf ditahan oleh QC (skor di bawah 7). Telegram tidak akan di-spam.")
        # Tetap kembalikan new_urls agar artikel ampas hari ini tidak dicek ulang besok
        return None, new_urls

    final_output = f"{briefing_text}\n\n🛡️ _QC Score: {score}/10 — {reason}_"
    return final_output, new_urls


def send_safe_message(chat_id, text):
    if not bot:
        print("❌ Bot instance tidak ditemukan.")
        return False
    try:
        bot.send_message(chat_id, text, disable_web_page_preview=True, parse_mode="Markdown")
        return True
    except Exception as e:
        print(f"⚠️ Gagal kirim via Markdown ({e}). Mencoba teks biasa...")
        try:
            bot.send_message(chat_id, text, disable_web_page_preview=True)
            return True
        except Exception as err:
            print(f"❌ Gagal total kirim ke Telegram ({chat_id}): {err}")
            return False


if __name__ == "__main__":
    is_cron_mode = "--cron" in sys.argv or os.getenv("RUN_MODE") == "cron"

    if is_cron_mode:
        print("🚀 Menjalankan AI Agency Bot dalam MODE CRON (GitHub Actions)...")

        target_chats = [cid.strip() for cid in [TELEGRAM_CHAT_ID, TELEGRAM_CHANNEL_ID] if cid]

        if not TELEGRAM_BOT_TOKEN or not target_chats:
            print("❌ Error: Secrets Telegram belum diset.")
            sys.exit(1)

        seen_urls = load_seen_news()
        print(f"🔎 Menyisir radar intel & bounty (Riwayat: {len(seen_urls)} data)...")

        try:
            report, new_urls = get_news_digest(seen_urls)

            if report:
                any_success = False
                for target in target_chats:
                    print(f"📤 Mengirim briefing ke Target: {target}...")
                    if send_safe_message(target, report):
                        any_success = True

                if any_success and new_urls:
                    seen_urls.update(new_urls)
                    save_seen_news(seen_urls)
                    print("✅ Berhasil dikirim dan state seen_news.json diperbarui.")
            elif new_urls:
                # Simpan URL yang ditolak QC supaya tidak diproses ulang besok
                seen_urls.update(new_urls)
                save_seen_news(seen_urls)
                print("🧹 URL berkualitas rendah sudah ditandai seen tanpa spam ke Telegram.")
            else:
                print("ℹ️ Tidak ada entri baru hari ini.")

            sys.exit(0)
        except Exception as e:
            print(f"❌ Terjadi error: {e}")
            sys.exit(1)
    else:
        print("🤖 Bot interaktif aktif (Mode Polling)...")
        if bot:
            bot.infinity_polling()
        else:
            print("❌ Error: TELEGRAM_BOT_TOKEN belum diset.")
