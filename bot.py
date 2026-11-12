import os
import sqlite3
import logging
import re
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

# -------------------- 24/7 KEEP ALIVE WEB SERVER --------------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is Running 24/7!")

    def log_message(self, format, *args):
        # Console spamming bondho rakhar jonno log off
        return

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# -------------------- CONFIGURATION --------------------
TOKEN = "8968939053:AAFtyTiXIKIFxsfqg4P-cu5Vvx-9X2tvt0M"
ADMIN_IDS = [8298133943]  # Telegram user ID
CHANNELS = ["@bdgiveaways24", "@bdgivewaychat", "@Pythonchecker1", "@ProApkHub_Official"] # Force join channels

# Bonus amounts
WELCOME_BONUS = 2
REFERRAL_BONUS_REFERRER = 5
REFERRAL_BONUS_REFERRED = 0

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    coins INTEGER DEFAULT 0,
                    referred_by INTEGER DEFAULT NULL,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    welcome_bonus_given BOOLEAN DEFAULT 0,
                    is_banned BOOLEAN DEFAULT 0
                )''')
    # Files table
    c.execute('''CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    price INTEGER NOT NULL
                )''')
    # Redeem codes table
    c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
                    code TEXT PRIMARY KEY,
                    reward_coins INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    used_by TEXT DEFAULT NULL,
                    expiry TIMESTAMP DEFAULT NULL,
                    created_by INTEGER NOT NULL
                )''')
    # Referrals table
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer INTEGER NOT NULL,
                    referred INTEGER NOT NULL,
                    reward_given BOOLEAN DEFAULT 0,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

init_db()

# -------------------- HELPER FUNCTIONS --------------------
def get_user_coins(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def add_coins(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def deduct_coins(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_all_files():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, file_id, file_name, price FROM files")
    files = c.fetchall()
    conn.close()
    return files

def add_file(file_id, file_name, price):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO files (file_id, file_name, price) VALUES (?, ?, ?)", (file_id, file_name, price))
    conn.commit()
    conn.close()

def delete_file(file_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

def create_redeem_code(code, reward, max_uses, admin_id, expiry_days=7):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO redeem_codes (code, reward_coins, max_uses, created_by, expiry) VALUES (?, ?, ?, ?, ?)",
              (code, reward, max_uses, admin_id, expiry))
    conn.commit()
    conn.close()

def use_redeem_code(user_id, code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT reward_coins, max_uses, used_count, used_by, expiry FROM redeem_codes WHERE code = ?", (code,))
    result = c.fetchone()
    if not result:
        conn.close()
        return False, "❌ Invalid code."
    reward, max_uses, used_count, used_by_str, expiry = result
    used_by_list = used_by_str.split(',') if used_by_str else []
    if str(user_id) in used_by_list:
        conn.close()
        return False, "❌ You have already used this code."
    if used_count >= max_uses:
        conn.close()
        return False, "❌ Code usage limit reached."
    if expiry and datetime.now() > datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S"):
        conn.close()
        return False, "❌ Code expired."
    new_used_count = used_count + 1
    new_used_by = ','.join(used_by_list + [str(user_id)])
    c.execute("UPDATE redeem_codes SET used_count = ?, used_by = ? WHERE code = ?", (new_used_count, new_used_by, code))
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, user_id))
    conn.commit()
    conn.close()
    return True, f"✅ Successfully redeemed {reward} coins!"

def add_user(user_id, username, referred_by=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, referred_by) VALUES (?, ?, ?)",
              (user_id, username, referred_by))
    conn.commit()
    conn.close()

def set_welcome_bonus_given(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET welcome_bonus_given = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_welcome_bonus_given(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT welcome_bonus_given FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] == 1 if result else False

def record_referral(referrer, referred):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO referrals (referrer, referred) VALUES (?, ?)", (referrer, referred))
    conn.commit()
    conn.close()

def is_referral_reward_given(referrer, referred):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT reward_given FROM referrals WHERE referrer = ? AND referred = ?", (referrer, referred))
    result = c.fetchone()
    conn.close()
    return result[0] == 1 if result else False

def give_referral_bonus(referrer, referred):
    if not is_referral_reward_given(referrer, referred):
        add_coins(referrer, REFERRAL_BONUS_REFERRER)
        add_coins(referred, REFERRAL_BONUS_REFERRED)
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE referrals SET reward_given = 1 WHERE referrer = ? AND referred = ?", (referrer, referred))
        conn.commit()
        conn.close()
        return True
    return False

def get_referral_link(user_id, bot_username):
    return f"https://t.me/{bot_username}?start=ref_{user_id}"

def is_user_banned(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] == 1 if result else False

def ban_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    return [row[0] for row in users]

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def check_force_join(user_id, context: ContextTypes.DEFAULT_TYPE):
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            return False
    return True

async def force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for channel in CHANNELS:
        keyboard.append([InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel[1:]}")])
    keyboard.append([InlineKeyboardButton("✅ I have joined", callback_data="check_join")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚫 Access Denied!\n\nYou must join the following channels to use this bot:",
        reply_markup=reply_markup
    )

# -------------------- USER COMMANDS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "NoUsername"

    if is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    if not await check_force_join(user_id, context):
        await force_join_message(update, context)
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = c.fetchone()
    conn.close()

    referred_by = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referred_by = int(context.args[0][4:])
            if referred_by == user_id:
                referred_by = None
        except:
            pass

    if not exists:
        add_user(user_id, username, referred_by)
        if not is_welcome_bonus_given(user_id):
            add_coins(user_id, WELCOME_BONUS)
            set_welcome_bonus_given(user_id)
            welcome_text = f"🎉 Welcome! You received {WELCOME_BONUS} coins as a welcome bonus."
        else:
            welcome_text = "Welcome!"

        if referred_by:
            record_referral(referred_by, user_id)
            give_referral_bonus(referred_by, user_id)
            try:
                await context.bot.send_message(
                    chat_id=referred_by,
                    text=f"🎉 New Referral Alert!\n\nUser @{username} joined using your link.\nYou earned +{REFERRAL_BONUS_REFERRER} coins!\nYour referred friend also got {REFERRAL_BONUS_REFERRED} coins."
                )
            except Exception as e:
                logger.error(f"Failed to notify referrer {referred_by}: {e}")
    else:
        welcome_text = "Welcome back!"

    keyboard = [
        ["📁 Buy Files", "💰 My Coins"],
        ["🔗 Referral Link", "🎫 Redeem Code"]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append(["👑 Admin Panel"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_msg = (
        f"{welcome_text}\n\n"
        f"✨ Welcome to {context.bot.first_name} ✨\n\n"
        f"Here you can buy premium files using coins.\n\n"
        f"How to earn coins:\n"
        f"• Invite friends using your referral link\n"
        f"• Use redeem codes (if any)\n"
        f"• Daily login bonus (coming soon)\n\n"
        f"Your current balance: {get_user_coins(user_id)} coins\n\n"
        f"Use the buttons below to navigate."
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

async def buy_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
        return
    if not await check_force_join(user_id, context):
        await force_join_message(update, context)
        return

    files = get_all_files()
    if not files:
        await update.message.reply_text("❌ No files available for purchase yet.")
        return

    keyboard = []
    for file in files:
        file_id = file[0]
        file_name = file[2]
        price = file[3]
        keyboard.append([InlineKeyboardButton(f"{file_name} - {price} coins", callback_data=f"buy_{file_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📂 Available Files:\nSelect a file to buy.", reply_markup=reply_markup)

async def my_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
        return
    if not await check_force_join(user_id, context):
        await force_join_message(update, context)
        return

    coins = get_user_coins(user_id)
    await update.message.reply_text(f"💰 Your Coin Balance: {coins} coins")

async def referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
        return
    if not await check_force_join(user_id, context):
        await force_join_message(update, context)
        return

    bot_username = (await context.bot.get_me()).username
    link = get_referral_link(user_id, bot_username)
    await update.message.reply_text(
        f"🔗 Your Referral Link:\n{link}\n\n"
        f"Share this link with friends. When they join, you get +{REFERRAL_BONUS_REFERRER} coins and they get +{REFERRAL_BONUS_REFERRED} coins!"
    )

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
        return
    if not await check_force_join(user_id, context):
        await force_join_message(update, context)
        return

    await update.message.reply_text("🎫 Please send your redeem code:")
    context.user_data['awaiting_redeem'] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get('awaiting_redeem'):
        code = text.strip()
        success, msg = use_redeem_code(user_id, code)
        await update.message.reply_text(msg)
        context.user_data['awaiting_redeem'] = False
        return

    if text == "📁 Buy Files":
        await buy_files(update, context)
    elif text == "💰 My Coins":
        await my_coins(update, context)
    elif text == "🔗 Referral Link":
        await referral_link(update, context)
    elif text == "🎫 Redeem Code":
        await redeem_code(update, context)
    else:
        if user_id in ADMIN_IDS:
            await handle_admin_input(update, context)
        else:
            await update.message.reply_text("Please use the buttons below to navigate.")

# -------------------- ADMIN COMMANDS --------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ You are not authorized.")
        return

    keyboard = [
        ["📢 Broadcast", "🎫 Create Redeem Code"],
        ["📁 Add File", "🗑 Delete File"],
        ["🚫 Ban User", "✅ Unban User"],
        ["📊 Stats", "❌ Close"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔧 Admin Panel\nChoose an action:", reply_markup=reply_markup)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    await update.message.reply_text("📢 Send the message you want to broadcast (text only):")
    context.user_data['awaiting_broadcast'] = True

async def create_redeem_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "🎫 Create Redeem Code\n\nSend details in this format:\ncode_name reward_coins max_uses\n\nExample: SUMMER50 50 100"
    )
    context.user_data['awaiting_redeem_create'] = True

async def add_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "📁 Add File\n\nPlease send the file (document) now.\nAfter that I'll ask for the price."
    )
    context.user_data['awaiting_file'] = True

async def delete_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    files = get_all_files()
    if not files:
        await update.message.reply_text("No files to delete.")
        return
    keyboard = []
    for file in files:
        file_id = file[0]
        file_name = file[2]
        price = file[3]
        keyboard.append([InlineKeyboardButton(f"{file_name} ({price} coins)", callback_data=f"del_{file_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select file to delete:", reply_markup=reply_markup)

async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    await update.message.reply_text("🚫 Ban User\n\nSend the user ID to ban:")
    context.user_data['awaiting_ban'] = True

async def unban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    await update.message.reply_text("✅ Unban User\n\nSend the user ID to unban:")
    context.user_data['awaiting_unban'] = True

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT SUM(coins) FROM users")
    total_coins = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM files")
    total_files = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM redeem_codes")
    total_codes = c.fetchone()[0]
    conn.close()
    msg = (
        f"📊 Bot Statistics\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💰 Total Coins: {total_coins}\n"
        f"📁 Files: {total_files}\n"
        f"🎫 Redeem Codes: {total_codes}"
    )
    await update.message.reply_text(msg)

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    text = update.message.text.strip()

    if context.user_data.get('awaiting_file_price'):
        try:
            price = int(text)
            if price <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Please enter a positive integer.")
            return
        file_id = context.user_data.get('temp_file_id')
        file_name = context.user_data.get('temp_file_name')
        if not file_id or not file_name:
            await update.message.reply_text("❌ File upload session expired. Please start again.")
            context.user_data['awaiting_file_price'] = False
            context.user_data.pop('temp_file_id', None)
            context.user_data.pop('temp_file_name', None)
            return
        add_file(file_id, file_name, price)
        await update.message.reply_text(f"✅ File added:\n📄 {file_name} – {price} coins")
        context.user_data['awaiting_file_price'] = False
        context.user_data.pop('temp_file_id', None)
        context.user_data.pop('temp_file_name', None)
        return

    if context.user_data.get('awaiting_broadcast'):
        broadcast_text = text
        users = get_all_users()
        success = 0
        fail = 0
        for uid in users:
            try:
                await context.bot.send_message(chat_id=uid, text=broadcast_text)
                success += 1
            except:
                fail += 1
        await update.message.reply_text(f"📢 Broadcast complete!\n✅ Success: {success}\n❌ Failed: {fail}")
        context.user_data['awaiting_broadcast'] = False
        return

    if context.user_data.get('awaiting_redeem_create'):
        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text("❌ Invalid format. Use: code_name reward_coins max_uses")
            context.user_data['awaiting_redeem_create'] = False
            return
        code, reward, max_uses = parts[0], parts[1], parts[2]
        try:
            reward = int(reward)
            max_uses = int(max_uses)
            if reward <= 0 or max_uses <= 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ Reward and max uses must be positive integers.")
            context.user_data['awaiting_redeem_create'] = False
            return
        create_redeem_code(code, reward, max_uses, user_id)
        expiry_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ Redeem Code Created Successfully!\n\n"
            f"📝 Code: {code}\n"
            f"💰 Reward: {reward} coins\n"
            f"👥 Max Uses: {max_uses} times\n"
            f"⏳ Expires: {expiry_date}\n\n"
            f"Share this code with users to claim their coins."
        )
        context.user_data['awaiting_redeem_create'] = False
        return

    if context.user_data.get('awaiting_ban'):
        try:
            target_id = int(text)
        except:
            await update.message.reply_text("❌ Invalid user ID.")
            context.user_data['awaiting_ban'] = False
            return
        ban_user(target_id)
        await update.message.reply_text(f"✅ User {target_id} banned.")
        context.user_data['awaiting_ban'] = False
        return

    if context.user_data.get('awaiting_unban'):
        try:
            target_id = int(text)
        except:
            await update.message.reply_text("❌ Invalid user ID.")
            context.user_data['awaiting_unban'] = False
            return
        unban_user(target_id)
        await update.message.reply_text(f"✅ User {target_id} unbanned.")
        context.user_data['awaiting_unban'] = False
        return

    if text == "👑 Admin Panel":
        await admin_panel(update, context)
    elif text == "📢 Broadcast":
        await broadcast(update, context)
    elif text == "🎫 Create Redeem Code":
        await create_redeem_code_start(update, context)
    elif text == "📁 Add File":
        await add_file_start(update, context)
    elif text == "🗑 Delete File":
        await delete_file_start(update, context)
    elif text == "🚫 Ban User":
        await ban_user_start(update, context)
    elif text == "✅ Unban User":
        await unban_user_start(update, context)
    elif text == "📊 Stats":
        await stats(update, context)
    elif text == "❌ Close":
        keyboard = [
            ["📁 Buy Files", "💰 My Coins"],
            ["🔗 Referral Link", "🎫 Redeem Code"]
        ]
        if user_id in ADMIN_IDS:
            keyboard.append(["👑 Admin Panel"])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Exited admin panel.", reply_markup=reply_markup)
    else:
        await update.message.reply_text("❓ Unknown command. Please use the admin panel buttons.")

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    if context.user_data.get('awaiting_file'):
        document = update.message.document
        if not document:
            await update.message.reply_text("Please send a file (document).")
            return
        file_id = document.file_id
        file_name = document.file_name or "unknown"
        context.user_data['temp_file_id'] = file_id
        context.user_data['temp_file_name'] = file_name
        await update.message.reply_text(
            "📄 File received.\nNow send the price in coins (positive integer):"
        )
        context.user_data['awaiting_file_price'] = True
        context.user_data['awaiting_file'] = False
    else:
        await update.message.reply_text("You are not in file upload mode. Use the admin panel to add a file.")

# -------------------- CALLBACK QUERY HANDLERS --------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "check_join":
        user_id = query.from_user.id
        if await check_force_join(user_id, context):
            await query.edit_message_text("✅ You have joined all channels. Use /start to continue.")
            await start(update, context)
        else:
            await query.edit_message_text("❌ You haven't joined all channels. Please join and try again.")
        return

    if data.startswith("buy_"):
        file_id = int(data.split("_")[1])
        user_id = query.from_user.id
        if is_user_banned(user_id):
            await query.edit_message_text("🚫 You are banned.")
            return
        if not await check_force_join(user_id, context):
            await force_join_message(update, context)
            return

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT file_id, file_name, price FROM files WHERE id = ?", (file_id,))
        file = c.fetchone()
        conn.close()
        if not file:
            await query.edit_message_text("File not found.")
            return
        file_id_tele, file_name, price = file
        user_coins = get_user_coins(user_id)
        if user_coins < price:
            await query.edit_message_text(
                f"❌ Insufficient coins!\n\n💰 Your balance: {user_coins} coins\n💸 Required: {price} coins"
            )
            return
        try:
            await context.bot.send_document(
                chat_id=user_id,
                document=file_id_tele,
                caption=f"✅ You purchased {file_name} for {price} coins."
            )
            deduct_coins(user_id, price)
            await query.edit_message_text(f"✅ File sent! Remaining coins: {get_user_coins(user_id)}")
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to send file. Please try again later.\nError: {str(e)[:50]}")
            logger.error(f"Error sending file: {e}")

    elif data.startswith("del_"):
        file_id = int(data.split("_")[1])
        delete_file(file_id)
        await query.edit_message_text("✅ File deleted.")

# -------------------- MAIN --------------------
def main():
    # Keep-Alive Server chalu kora (UptimeRobot er jonno)
    keep_alive()

    # Telegram bot start kora
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
