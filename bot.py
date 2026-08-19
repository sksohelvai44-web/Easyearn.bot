# bot.py
import logging
import sqlite3
import random
import string
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ==================== CONFIGURATION ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # @BotFather থেকে নিন
ADMIN_IDS = [123456789]  # আপনার Telegram ID দিন
MIN_WITHDRAW = 50.00
INSTAGRAM_REWARD = 50.00
REFERRAL_COMMISSION = 10  # 10%
VIDEO_TUTORIAL = "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"

# Conversation States
ASK_2FA, ASK_WITHDRAW_NUMBER, ASK_WITHDRAW_AMOUNT = range(3)

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("taskly.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Users Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                balance REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_earnings REAL DEFAULT 0,
                language TEXT DEFAULT 'bn',
                is_banned INTEGER DEFAULT 0
            )
        ''')
        
        # Instagram Tasks Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS instagram_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT UNIQUE,
                password TEXT,
                twofa_code TEXT,
                authenticator_code TEXT,
                status TEXT DEFAULT 'pending',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                reward REAL DEFAULT 50.00,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Task History Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_type TEXT,
                task_id INTEGER,
                reward REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Withdrawals Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                account_number TEXT,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Referrals Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                commission REAL DEFAULT 0,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (id),
                FOREIGN KEY (referred_id) REFERENCES users (id)
            )
        ''')
        
        self.conn.commit()
    
    def get_user(self, telegram_id):
        self.cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return self.cursor.fetchone()
    
    def create_user(self, telegram_id, username, first_name, referred_by=None):
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        self.cursor.execute('''
            INSERT INTO users (telegram_id, username, first_name, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (telegram_id, username, first_name, referral_code, referred_by))
        self.conn.commit()
        
        if referred_by:
            self.add_referral_commission(referred_by, telegram_id)
        
        return self.get_user(telegram_id)
    
    def get_user_by_referral(self, referral_code):
        self.cursor.execute("SELECT telegram_id FROM users WHERE referral_code = ?", (referral_code,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def add_referral_commission(self, referrer_id, referred_id):
        commission = 10.00
        self.cursor.execute('''
            UPDATE users SET balance = balance + ?, referral_earnings = referral_earnings + ?
            WHERE telegram_id = ?
        ''', (commission, commission, referrer_id))
        
        self.cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id, commission)
            VALUES (?, ?, ?)
        ''', (referrer_id, referred_id, commission))
        self.conn.commit()
    
    def create_instagram_task(self, user_id, username, password):
        self.cursor.execute('''
            INSERT INTO instagram_tasks (user_id, username, password, status)
            VALUES (?, ?, ?, 'pending')
        ''', (user_id, username, password))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def update_instagram_task(self, task_id, status, twofa_code=None, authenticator_code=None):
        self.cursor.execute('''
            UPDATE instagram_tasks 
            SET status = ?, twofa_code = ?, authenticator_code = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, twofa_code, authenticator_code, task_id))
        self.conn.commit()
    
    def add_balance(self, user_id, amount):
        self.cursor.execute('''
            UPDATE users SET balance = balance + ?, total_earned = total_earned + ?
            WHERE id = ?
        ''', (amount, amount, user_id))
        self.conn.commit()
    
    def create_withdrawal(self, user_id, amount, method, account_number):
        self.cursor.execute('''
            INSERT INTO withdrawals (user_id, amount, method, account_number, status)
            VALUES (?, ?, ?, ?, 'pending')
        ''', (user_id, amount, method, account_number))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_pending_withdrawals(self):
        self.cursor.execute('''
            SELECT w.*, u.username, u.first_name 
            FROM withdrawals w
            JOIN users u ON w.user_id = u.id
            WHERE w.status = 'pending'
            ORDER BY w.requested_at ASC
        ''')
        return self.cursor.fetchall()
    
    def update_withdrawal_status(self, withdrawal_id, status):
        self.cursor.execute('''
            UPDATE withdrawals SET status = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, withdrawal_id))
        self.conn.commit()
    
    def get_user_language(self, telegram_id):
        user = self.get_user(telegram_id)
        return user[9] if user else 'bn'  # language is at index 9
    
    def update_language(self, telegram_id, lang):
        self.cursor.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (lang, telegram_id))
        self.conn.commit()
    
    def get_task_count(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM task_history WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()[0]
    
    def get_completed_count(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM task_history WHERE user_id = ? AND status = 'completed'", (user_id,))
        return self.cursor.fetchone()[0]
    
    def get_pending_count(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM task_history WHERE user_id = ? AND status = 'pending'", (user_id,))
        return self.cursor.fetchone()[0]
    
    def get_referral_count(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        return self.cursor.fetchone()[0]
    
    def close(self):
        self.conn.close()

# ==================== TEXTS ====================
TEXTS = {
    'bn': {
        'welcome': "👋 স্বাগতম Task Bot-এ!\n\n📌 এই বটে কাজ করে টাকা আয় করুন।\n\n📜 শর্তাবলী মেনে চলতে হবে।\n\n✅ নিচের বাটনে ক্লিক করে শুরু করুন",
        'main_menu': "🏠 মেইন মেনু\n\nআপনি কী করতে চান?",
        'task_menu': "📋 টাস্ক সিলেক্ট করুন:\n\nআপনি কোন টাস্ক করতে চান?",
        'instagram_desc': "⏳ রিভিউ সময়: ২৪ ঘন্টা\n\n📋 টাস্ক: 📱 ইনস্টাগ্রাম (২FA) তৈরি করুন\n\n📄 বিবরণ: আপনাকে অবশ্যই একটি নতুন ইনস্টাগ্রাম অ্যাকাউন্ট তৈরি করতে হবে শুধুমাত্র মোবাইল ডিভাইস ব্যবহার করে।\n🔐 আবশ্যক!\nআপনাকে অবশ্যই টেলিগ্রাম বট দ্বারা প্রদত্ত তথ্য ব্যবহার করতে হবে।\n\n❗আপনি যদি নিজের তথ্য ব্যবহার করেন, আপনার আবেদন যাচাই ছাড়াই বাতিল করা হবে।\n\nরেজিস্ট্রেশনের পর:\n👉 কোনো তথ্য পাঠানোর প্রয়োজন নেই\n✅ শুধু 'অ্যাকাউন্ট রেজিস্টার্ড' বাটনে ক্লিক করুন\n\n⏳ রিভিউ সময়: ২৪ ঘন্টা",
        'credentials': "✅ অ্যাকাউন্ট তৈরি করা হয়েছে!\n\n👤 ইউজারনেম: {}\n🔑 পাসওয়ার্ড: {}\n\n📌 এই ক্রেডেনশিয়াল ব্যবহার করে লগইন করুন এবং রেজিস্ট্রেশন সম্পূর্ণ করুন।",
        'ask_2fa': "📱 আপনার Google Authenticator থেকে 2FA কোড দিন:\n\nউদাহরণ: 123456\n\n(শুধু ৬ ডিজিটের সংখ্যা দিন)",
        'authenticator_code': "✅ 2FA কোড গৃহীত হয়েছে: {}\n\n🔄 ভেরিফিকেশন কোড জেনারেট করা হচ্ছে...\n✅ আপনার ইনস্টাগ্রাম 2FA ভেরিফিকেশন কোড: {}\n\n📌 ইনস্টাগ্রাম অ্যাপে এই কোডটি দিন।",
        'task_complete': "✅ টাস্ক সম্পূর্ণ হয়েছে!\n\n⏳ আপনার টাস্ক রিভিউতে রয়েছে। ২৪ ঘন্টার মধ্যে রিওয়ার্ড পাবেন।\n\n💰 রিওয়ার্ড: ৫০.০০ টাকা (পেন্ডিং)",
        'balance': "💰 আপনার ব্যালেন্স\n\n📊 মোট ব্যালেন্স: {:.2f} টাকা\n📈 মোট আয়: {:.2f} টাকা\n⏳ পেন্ডিং: {:.2f} টাকা",
        'withdraw': "💳 টাকা তোলা\n\n💰 আপনার ব্যালেন্স: {:.2f} টাকা\n⚠️ মিনিমাম উইথড্রো: ৫০.০০ টাকা\n\nউইথড্রো পদ্ধতি সিলেক্ট করুন:",
        'withdraw_details': "📱 আপনার {} অ্যাকাউন্ট নম্বর দিন:\n\nউদাহরণ: 01XXXXXXXXX",
        'withdraw_amount': "💰 কত টাকা তুলতে চান?\n\nমিনিমাম: {:.2f} টাকা\nম্যাক্সিমাম: {:.2f} টাকা",
        'withdraw_success': "✅ উইথড্রো রিকোয়েস্ট জমা হয়েছে!\n\n📱 মেথড: {}\n📞 নাম্বার: {}\n💰 টাকা: {:.2f} টাকা\n\n⏳ আপনার রিকোয়েস্ট পেন্ডিং। ২৪ ঘন্টার মধ্যে পেমেন্ট পাবেন।",
        'profile': "👤 আপনার প্রোফাইল\n\n🆔 আইডি: {}\n👤 ইউজারনেম: @{}\n📅 জয়েন করেছেন: {}\n💰 ব্যালেন্স: {:.2f} টাকা\n🏆 মোট টাস্ক: {}\n✅ সম্পূর্ণ: {}\n⏳ পেন্ডিং: {}",
        'refer': "🔗 রেফারেল প্রোগ্রাম\n\n💰 সারাজীবন ১০% কমিশন আয় করুন!\n\nআপনার রেফারেল লিংক:\n`https://t.me/YourBot?start=ref_{}`\n\n📊 আপনার স্ট্যাটস:\n👥 মোট রেফারেল: {}\n💰 কমিশন আয়: {:.2f} টাকা",
        'language': "🌐 ভাষা সিলেক্ট করুন / Select Language:",
        'language_changed': "✅ ভাষা পরিবর্তন করা হয়েছে!",
        'back_to_menu': "🏠 মেইন মেনুতে ফিরে যাচ্ছি...",
        'cancel': "❌ বাতিল করা হয়েছে!",
        'invalid_input': "❌ ভুল ইনপুট! আবার চেষ্টা করুন।",
        'video': "🎥 টিউটোরিয়াল ভিডিও:\n{}",
        'no_balance': "❌ আপনার ব্যালেন্স পর্যাপ্ত নয়!\n\nমিনিমাম উইথড্রো: ৫০.০০ টাকা",
        'invalid_number': "❌ ভুল ফোন নম্বর! সঠিক ফরম্যাটে দিন (যেমন: 018XXXXXXXX)",
        'invalid_amount': "❌ ভুল টাকার পরিমাণ! মিনিমাম ৫০ টাকা এবং আপনার ব্যালেন্সের বেশি হতে পারবে না।",
        'already_started': "❌ আপনার ইতিমধ্যেই একটি এক্টিভ টাস্ক আছে! আগেরটা শেষ করুন।"
    },
    'en': {
        'welcome': "👋 Welcome to Task Bot!\n\n📌 Earn money by doing simple tasks.\n\n📜 Terms of Use apply.\n\n✅ Click the button below to start",
        'main_menu': "🏠 Main Menu\n\nWhat would you like to do?",
        'task_menu': "📋 Select Task Type:\n\nWhich task would you like to do?",
        'instagram_desc': "⏳ Review time: 24 hours\n\n📋 Task: 📱 Create Inst (2FA)\n\n📄 Description: In this task, you must create a new Inst acc using only a real mobile device.\n🔐 REQUIRED!\nYou must use the information provided by the Telegram bot to register.\n\n❗If you use your own information, your application will be REJECTED without verification.\n\nAfter registration:\n👉 No need to send any info\n✅ Just click the 'Account Registered' button\n\n⏳ Review time: 24 hours",
        'credentials': "✅ Account Created Successfully!\n\n👤 Username: {}\n🔑 Password: {}\n\n📌 Please login with these credentials and complete the registration.",
        'ask_2fa': "📱 Please enter your 2FA code from Google Authenticator:\n\nExample: 123456\n\n(Only 6 digits)",
        'authenticator_code': "✅ 2FA Code Received: {}\n\n🔄 Generating verification code...\n✅ Your Instagram 2FA verification code is: {}\n\n📌 Please enter this code in your Instagram app to complete 2FA setup.",
        'task_complete': "✅ Task Completed Successfully!\n\n⏳ Your task is under review. You will receive reward within 24 hours.\n\n💰 Reward: 50.00 BDT (Pending)",
        'balance': "💰 Your Balance\n\n📊 Total Balance: {:.2f} BDT\n📈 Total Earned: {:.2f} BDT\n⏳ Pending: {:.2f} BDT",
        'withdraw': "💳 Withdraw Money\n\n💰 Your Balance: {:.2f} BDT\n⚠️ Minimum Withdrawal: 50.00 BDT\n\nSelect withdrawal method:",
        'withdraw_details': "📱 Enter your {} account number:\n\nExample: 01XXXXXXXXX",
        'withdraw_amount': "💰 How much do you want to withdraw?\n\nMinimum: {:.2f} BDT\nMaximum: {:.2f} BDT",
        'withdraw_success': "✅ Withdrawal Request Submitted!\n\n📱 Method: {}\n📞 Number: {}\n💰 Amount: {:.2f} BDT\n\n⏳ Your request is pending. You will receive payment within 24 hours.",
        'profile': "👤 Your Profile\n\n🆔 ID: {}\n👤 Username: @{}\n📅 Joined: {}\n💰 Balance: {:.2f} BDT\n🏆 Total Tasks: {}\n✅ Completed: {}\n⏳ Pending: {}",
        'refer': "🔗 Referral Program\n\n💰 Earn 10% commission for life!\n\nYour referral link:\n`https://t.me/YourBot?start=ref_{}`\n\n📊 Your Stats:\n👥 Total Referrals: {}\n💰 Commission Earned: {:.2f} BDT",
        'language': "🌐 Select Language / ভাষা নির্বাচন করুন:",
        'language_changed': "✅ Language changed successfully!",
        'back_to_menu': "🏠 Returning to Main Menu...",
        'cancel': "❌ Cancelled!",
        'invalid_input': "❌ Invalid input! Please try again.",
        'video': "🎥 Tutorial Video:\n{}",
        'no_balance': "❌ Insufficient balance!\n\nMinimum withdrawal: 50.00 BDT",
        'invalid_number': "❌ Invalid phone number! Use correct format (e.g., 018XXXXXXXX)",
        'invalid_amount': "❌ Invalid amount! Minimum 50 BDT and cannot exceed your balance.",
        'already_started': "❌ You already have an active task! Please complete it first."
    }
}

# ==================== HELPERS ====================
def generate_credentials():
    username = "insta_user_" + ''.join(random.choices(string.digits, k=4))
    password = "P@ssW0rd#" + ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return username, password

def generate_authenticator_code():
    return ''.join(random.choices(string.digits, k=6))

def generate_2fa_code():
    return ''.join(random.choices(string.digits, k=6))

def get_text(user_id, key, *args):
    lang = db.get_user_language(user_id)
    text = TEXTS.get(lang, TEXTS['bn']).get(key, key)
    if args:
        return text.format(*args)
    return text

# ==================== KEYBOARDS ====================
def get_main_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("📋 Task", callback_data="task")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💳 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("🔗 Refer", callback_data="refer")],
        [InlineKeyboardButton("🌐 Language", callback_data="language")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_task_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("📱 Instagram 2FA", callback_data="task_instagram")],
        [InlineKeyboardButton("📘 Facebook", callback_data="task_facebook")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_instagram_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("✅ Start", callback_data="inst_start")],
        [InlineKeyboardButton("🎥 Video", callback_data="inst_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_twofa_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("🔐 Set 2FA", callback_data="inst_set_2fa")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_done_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("✅ Done", callback_data="inst_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_withdraw_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton("📱 Bkash", callback_data="withdraw_bkash")],
        [InlineKeyboardButton("📱 Nagad", callback_data="withdraw_nagad")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_language_menu():
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_menu(user_id):
    lang = db.get_user_language(user_id)
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="cancel")]]
    return InlineKeyboardMarkup(keyboard)

# ==================== BOT HANDLERS ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# User states for multi-step conversations
user_data_store = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    username = user.username or "NoUsername"
    first_name = user.first_name or "User"
    
    # Check if user exists
    db_user = db.get_user(telegram_id)
    
    # Check for referral
    referred_by = None
    if context.args and context.args[0].startswith('ref_'):
        ref_code = context.args[0]
        referrer_id = db.get_user_by_referral(ref_code)
        if referrer_id and referrer_id != telegram_id:
            referred_by = referrer_id
    
    if not db_user:
        db.create_user(telegram_id, username, first_name, referred_by)
    
    text = get_text(telegram_id, 'welcome')
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Agree & Continue", callback_data="main_menu")]
        ])
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    # Cancel - Go to main menu
    if data == "cancel":
        user_data_store.pop(user_id, None)
        await query.edit_message_text(
            get_text(user_id, 'back_to_menu'),
            reply_markup=get_main_menu(user_id)
        )
        return
    
    # Main Menu
    if data == "main_menu":
        await query.edit_message_text(
            get_text(user_id, 'main_menu'),
            reply_markup=get_main_menu(user_id)
        )
        return
    
    # Task Menu
    if data == "task":
        await query.edit_message_text(
            get_text(user_id, 'task_menu'),
            reply_markup=get_task_menu(user_id)
        )
        return
    
    # Instagram Task
    if data == "task_instagram":
        text = get_text(user_id, 'instagram_desc')
        await query.edit_message_text(
            text,
            reply_markup=get_instagram_menu(user_id)
        )
        return
    
    # Facebook Task (Not implemented)
    if data == "task_facebook":
        await query.edit_message_text(
            "📘 Facebook task coming soon!\n\nStay tuned...",
            reply_markup=get_cancel_menu(user_id)
        )
        return
    
    # Instagram Start - Generate credentials
    if data == "inst_start":
        # Check if user already has active task
        # Simple check - we'll just allow one at a time
        username, password = generate_credentials()
        db_user = db.get_user(user_id)
        task_id = db.create_instagram_task(db_user[0], username, password)
        
        # Store task info in context
        user_data_store[user_id] = {'task_id': task_id, 'username': username, 'password': password}
        
        text = get_text(user_id, 'credentials', username, password)
        await query.edit_message_text(
            text,
            reply_markup=get_twofa_menu(user_id)
        )
        return
    
    # Instagram Video
    if data == "inst_video":
        text = get_text(user_id, 'video', VIDEO_TUTORIAL)
        await query.edit_message_text(
            text,
            reply_markup=get_instagram_menu(user_id)
        )
        return
    
    # Instagram Set 2FA - Ask for 2FA code
    if data == "inst_set_2fa":
        if user_id in user_data_store and 'task_id' in user_data_store[user_id]:
            text = get_text(user_id, 'ask_2fa')
            await query.edit_message_text(
                text,
                reply_markup=get_cancel_menu(user_id)
            )
            return ASK_2FA  # Start conversation
        else:
            await query.edit_message_text(
                "❌ No active task found!",
                reply_markup=get_main_menu(user_id)
            )
            return
    
    # Instagram Done
    if data == "inst_done":
        if user_id in user_data_store and 'task_id' in user_data_store[user_id]:
            task_id = user_data_store[user_id]['task_id']
            db_user = db.get_user(user_id)
            
            # Update task status
            db.update_instagram_task(task_id, 'completed')
            
            # Add reward
            db.add_balance(db_user[0], INSTAGRAM_REWARD)
            
            # Add to task history
            db.cursor.execute('''
                INSERT INTO task_history (user_id, task_type, task_id, reward, status)
                VALUES (?, ?, ?, ?, 'completed')
            ''', (db_user[0], 'instagram', task_id, INSTAGRAM_REWARD))
            db.conn.commit()
            
            user_data_store.pop(user_id, None)
            
            text = get_text(user_id, 'task_complete')
            await query.edit_message_text(
                text,
                reply_markup=get_main_menu(user_id)
            )
        else:
            await query.edit_message_text(
                "❌ No active task found!",
                reply_markup=get_main_menu(user_id)
            )
        return
    
    # Balance
    if data == "balance":
        db_user = db.get_user(user_id)
        text = get_text(user_id, 'balance', db_user[3], db_user[4], 0)  # balance, total_earned, pending
        await query.edit_message_text(
            text,
            reply_markup=get_main_menu(user_id)
        )
        return
    
    # Withdraw
    if data == "withdraw":
        db_user = db.get_user(user_id)
        if db_user[3] < MIN_WITHDRAW:
            await query.edit_message_text(
                get_text(user_id, 'no_balance'),
                reply_markup=get_main_menu(user_id)
            )
            return
        text = get_text(user_id, 'withdraw', db_user[3])
        await query.edit_message_text(
            text,
            reply_markup=get_withdraw_menu(user_id)
        )
        return
    
    # Withdraw Bkash / Nagad
    if data in ["withdraw_bkash", "withdraw_nagad"]:
        method = "Bkash" if data == "withdraw_bkash" else "Nagad"
        user_data_store[user_id] = {'withdraw_method': method}
        text = get_text(user_id, 'withdraw_details', method)
        await query.edit_message_text(
            text,
            reply_markup=get_cancel_menu(user_id)
        )
        return ASK_WITHDRAW_NUMBER
    
    # Profile
    if data == "profile":
        db_user = db.get_user(user_id)
        join_date = db_user[2][:10] if db_user[2] else "N/A"
        total_tasks = db.get_task_count(db_user[0])
        completed = db.get_completed_count(db_user[0])
        pending = db.get_pending_count(db_user[0])
        
        text = get_text(user_id, 'profile', 
                       user_id, 
                       db_user[1] or "NoUsername",
                       join_date,
                       db_user[3],
                       total_tasks,
                       completed,
                       pending)
        await query.edit_message_text(
            text,
            reply_markup=get_main_menu(user_id)
        )
        return
    
    # Refer
    if data == "refer":
        db_user = db.get_user(user_id)
        ref_count = db.get_referral_count(db_user[0])
        text = get_text(user_id, 'refer', 
                       db_user[6],  # referral_code
                       ref_count,
                       db_user[8])  # referral_earnings
        await query.edit_message_text(
            text,
            reply_markup=get_main_menu(user_id),
            parse_mode='Markdown'
        )
        return
    
    # Language
    if data == "language":
        await query.edit_message_text(
            get_text(user_id, 'language'),
            reply_markup=get_language_menu()
        )
        return
    
    # Language Change
    if data == "lang_en":
        db.update_language(user_id, 'en')
        await query.edit_message_text(
            get_text(user_id, 'language_changed'),
            reply_markup=get_main_menu(user_id)
        )
        return
    
    if data == "lang_bn":
        db.update_language(user_id, 'bn')
        await query.edit_message_text(
            get_text(user_id, 'language_changed'),
            reply_markup=get_main_menu(user_id)
        )
        return

# ==================== MESSAGE HANDLERS ====================
async def handle_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Check if it's a 6-digit number
    if not re.match(r'^\d{6}$', text):
        await update.message.reply_text(
            get_text(user_id, 'invalid_input'),
            reply_markup=get_cancel_menu(user_id)
        )
        return ASK_2FA
    
    if user_id not in user_data_store or 'task_id' not in user_data_store[user_id]:
        await update.message.reply_text(
            "❌ No active task!",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END
    
    # Generate authenticator code
    auth_code = generate_authenticator_code()
    
    # Update task with codes
    task_id = user_data_store[user_id]['task_id']
    db.update_instagram_task(task_id, 'pending', text, auth_code)
    
    # Store authenticator code for verification
    user_data_store[user_id]['auth_code'] = auth_code
    
    text_msg = get_text(user_id, 'authenticator_code', text, auth_code)
    await update.message.reply_text(
        text_msg,
        reply_markup=get_done_menu(user_id)
    )
    return ConversationHandler.END

async def handle_withdraw_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Validate phone number (Bangladeshi format)
    if not re.match(r'^01[3-9]\d{8}$', text):
        await update.message.reply_text(
            get_text(user_id, 'invalid_number'),
            reply_markup=get_cancel_menu(user_id)
        )
        return ASK_WITHDRAW_NUMBER
    
    # Store number and ask for amount
    user_data_store[user_id]['withdraw_number'] = text
    db_user = db.get_user(user_id)
    
    text_msg = get_text(user_id, 'withdraw_amount', MIN_WITHDRAW, db_user[3])
    await update.message.reply_text(
        text_msg,
        reply_markup=get_cancel_menu(user_id)
    )
    return ASK_WITHDRAW_AMOUNT

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(
            get_text(user_id, 'invalid_amount'),
            reply_markup=get_cancel_menu(user_id)
        )
        return ASK_WITHDRAW_AMOUNT
    
    db_user = db.get_user(user_id)
    
    if amount < MIN_WITHDRAW or amount > db_user[3]:
        await update.message.reply_text(
            get_text(user_id, 'invalid_amount'),
            reply_markup=get_cancel_menu(user_id)
        )
        return ASK_WITHDRAW_AMOUNT
    
    # Create withdrawal
    method = user_data_store[user_id]['withdraw_method']
    number = user_data_store[user_id]['withdraw_number']
    
    db.create_withdrawal(db_user[0], amount, method, number)
    
    # Deduct balance
    db.cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, db_user[0]))
    db.conn.commit()
    
    # Clear user data
    user_data_store.pop(user_id, None)
    
    text_msg = get_text(user_id, 'withdraw_success', method, number, amount)
    await update.message.reply_text(
        text_msg,
        reply_markup=get_main_menu(user_id)
    )
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_store.pop(user_id, None)
    await update.message.reply_text(
        get_text(user_id, 'cancel'),
        reply_markup=get_main_menu(user_id)
    )
    return ConversationHandler.END

# ==================== ADMIN COMMANDS ====================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    pending_withdrawals = db.get_pending_withdrawals()
    if not pending_withdrawals:
        await update.message.reply_text("✅ No pending withdrawals.")
        return
    
    msg = "📋 Pending Withdrawals:\n\n"
    for w in pending_withdrawals:
        msg += f"ID: {w[0]} | User: @{w[8]} | Amount: {w[2]} BDT | Method: {w[3]}\n"
    
    await update.message.reply_text(msg)

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /approve <withdrawal_id>")
        return
    
    try:
        w_id = int(context.args[0])
        db.update_withdrawal_status(w_id, 'approved')
        await update.message.reply_text(f"✅ Withdrawal {w_id} approved!")
    except:
        await update.message.reply_text("❌ Invalid ID!")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /reject <withdrawal_id>")
        return
    
    try:
        w_id = int(context.args[0])
        db.update_withdrawal_status(w_id, 'rejected')
        await update.message.reply_text(f"❌ Withdrawal {w_id} rejected!")
    except:
        await update.message.reply_text("❌ Invalid ID!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT SUM(balance) FROM users")
    total_balance = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
    pending_withdraw = db.cursor.fetchone()[0]
    
    msg = f"""
📊 Bot Statistics:

👥 Total Users: {total_users}
💰 Total Balance: {total_balance:.2f} BDT
⏳ Pending Withdrawals: {pending_withdraw}
    """
    await update.message.reply_text(msg)

# ==================== MAIN ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="inst_set_2fa")],
        states={
            ASK_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    
    withdraw_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(callback_handler, pattern="withdraw_bkash"),
            CallbackQueryHandler(callback_handler, pattern="withdraw_nagad"),
        ],
        states={
            ASK_WITHDRAW_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_number)],
            ASK_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("reject", reject))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(conv_handler)
    application.add_handler(withdraw_conv_handler)
    
    # Start bot
    print("🤖 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
