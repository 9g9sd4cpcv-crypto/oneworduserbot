import asyncio
import re
import time
from datetime import datetime
from typing import Dict, Set, Optional, List

from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserNotParticipant, ChatAdminRequired, RightsError
from pyrogram.types import Message, ChatMember, User

load_dotenv()
import os

# Environment Variables
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
OWNER_ID = int(os.getenv("OWNER_ID"))

# Initialize Pyrogram Client
app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION
)

# ==================== STORAGE ====================
word_chain_enabled: Dict[int, bool] = {}  # chat_id -> enabled
used_words: Dict[int, Set[str]] = {}  # chat_id -> set of used words
last_word_by_bot: Dict[int, str] = {}  # chat_id -> last word from bot

# ==================== HELPERS ====================

async def get_user_from_message(message: Message) -> Optional[User]:
    """Extract user from reply, text mention, or user_id/username"""
    if message.reply_to_message:
        return message.reply_to_message.from_user
    
    text = message.text or message.caption
    if not text:
        return None
    
    # Check for user_id/username in command
    parts = text.split()
    if len(parts) > 1:
        identifier = parts[1].strip().lstrip('@')
        try:
            if identifier.isdigit():
                return await app.get_users(int(identifier))
            else:
                return await app.get_users(identifier)
        except Exception:
            return None
    return None

async def get_chat_members(chat_id: int, filter_type: str = "all") -> List[User]:
    """Get members with batching and flood wait handling"""
    members = []
    offset = 0
    limit = 200
    
    while True:
        try:
            async for member in app.get_chat_members(chat_id, offset=offset, limit=limit):
                user = member.user
                
                if filter_type == "real":
                    # Exclude bots
                    if user.is_bot:
                        continue
                elif filter_type == "admins":
                    # Only admins
                    if not member.status in [enums.ChatMemberStatus.ADMIN, enums.ChatMemberStatus.OWNER]:
                        continue
                elif filter_type == "real_no_admins":
                    # Real users only, exclude admins
                    if user.is_bot:
                        continue
                    if member.status in [enums.ChatMemberStatus.ADMIN, enums.ChatMemberStatus.OWNER]:
                        continue
                
                members.append(user)
            
            if len(members) < limit:
                break
            offset += limit
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"Error getting members: {e}")
            break
    
    return members

async def mention_user(user: User) -> str:
    """Get mention string for user"""
    if user.username:
        return f"@{user.username}"
    return f"[{user.first_name}](tg://user?id={user.id})"

async def is_owner(user_id: int) -> bool:
    """Check if user is owner"""
    return user_id == OWNER_ID

async def is_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin in chat"""
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMIN, enums.ChatMemberStatus.OWNER]
    except:
        return False

async def can_modify(chat_id: int, user_id: int) -> bool:
    """Check if we can moderate this user"""
    # Can't moderate owner
    if user_id == OWNER_ID:
        return False
    
    # Can't moderate admins
    if await is_admin(chat_id, user_id):
        return False
    
    # Can't moderate bots
    try:
        member = await app.get_chat_member(chat_id, user_id)
        if member.user.is_bot:
            return False
    except:
        pass
    
    return True

def extract_last_letter(word: str) -> str:
    """Extract last letter, handling special cases"""
    word = word.upper().strip()
    if not word:
        return ''
    
    # Remove punctuation
    word = re.sub(r'[^\w]', '', word)
    if not word:
        return ''
    
    last_char = word[-1]
    
    # Handle common letter mappings
    if last_char in 'Xx':
        return 'X'
    if last_char in 'Zz':
        return 'Z'
    
    return last_char

def is_valid_word(word: str) -> bool:
    """Basic word validation"""
    word = word.strip().lower()
    if len(word) < 2:
        return False
    # Must be alphabetic only
    if not re.match(r'^[a-z]+$', word):
        return False
    return True

def find_next_word(last_letter: str, used_words_set: Set[str], chat_id: int) -> Optional[str]:
    """Find a valid next word starting with last_letter"""
    # Common English words dictionary (extend as needed)
    words = [
        "apple", "elephant", "tree", "ice", "egg", "guitar", "radio", "ocean", "noodle", "door",
        "rabbit", "tiger", "rain", "night", "hotel", "lemon", "monkey", "yellow", "window", "dolphin",
        "nest", "tea", "animal", "laptop", "panda", "airplane", "moon", "nose", "elbow", "water",
        "rainbow", "whale", "eagle", "eggplant", "giraffe", "flower", "river", "rocket", "turtle",
        "europe", "umbrella", "anchor", "robot", "tongue", "earth", "hat", "tiger", "ring", "grass",
        "snake", "elk", "kite", "explorer", "rose", "sun", "needle", "elevator", "raccoon", "notebook",
        "park", "key", "yogurt", "teapot", "train", "nail", "lamp", "piano", "octopus", "snow",
        "wallet", "teeth", "hornet", "tunnel", "ladder", "dream", "mouse", "escalator", "river",
        "violin", "nut", "taxi", "igloo", "unicorn", "nest", "telephone", "elephant", "tractor",
        "remote", "envelope", "eraser", "refrigerator", "thumb", "beach", "hiccup", "puzzle", "llama",
        "avocado", "orange", "egg", "ghost", "tornado", "oyster", "raccoon", "anchor", "reindeer",
        "emerald", "donut", "toast", "thermometer", "hourglass", "pinwheel", "lipstick", "treasure",
        "rhinoceros", "submarine", "eyelash", "helicopter", "jellyfish", "flamingo", "chimpanzee",
        "strawberry", "broccoli", "pineapple", "cheetah", "dinosaur", "kangaroo", "penguin", "squirrel",
        "crocodile", "butterfly", "caterpillar", "hedgehog", "chameleon", "porcupine", "seahorse",
        "peacock", "parrot", "peacock", "goldfish", "salamander", "chipmunk", "jaguar", "panther",
        "panorama", "armadillo", "bandicoot", "blue whale", "cormorant", "dingo", "emu", "falcon",
        "gazelle", "hamster", "iguana", "jellybean", "kiwi", "lemur", "marmot", "narwhal", "ocelot",
        "pangolin", "quokka", "rhino", "sloth", "tapir", "vicuna", "wombat", "xerus", "yak", "zebra",
        "airplane", "boat", "car", "drone", "engine", "ferry", "glider", "hovercraft", "jet", "kayak",
        "locomotive", "motorcycle", "navigator", "orbiter", "plane", "quad", "rocket", "shuttle",
        "tanker", "unicycle", "vehicle", "wagon", "yacht", "zeplin", "astronaut", "balloon", "captain",
        "diver", "explorer", "farmer", "gardener", "hermit", "inventor", "janitor", "knight",
        "lawyer", "magician", "nurse", "officer", "pilot", "queen", "ranger", "sailor", "tourist",
        "umpire", "valley", "warden", "xenon", "yogi", "zookeeper", "artist", "baker", "chef",
        "doctor", "engineer", "fireman", "geologist", "hunter", "inspector", "journalist", "king",
        "lumberjack", "mechanic", "newspaper", "optician", "plumber", "quarryman", "reporter",
        "scientist", "therapist", "undertaker", "veterinarian", "welder", "xylophonist", "zoologist"
    ]
    
    # Also add more words starting with each letter
    extended_words = {
        'A': ['apple', 'ant', 'airplane', 'arrow', 'anchor', 'avocado', 'apartment', 'artist', 'astronaut', 'alligator'],
        'B': ['ball', 'banana', 'book', 'bear', 'bird', 'boat', 'bread', 'bridge', 'butterfly', 'bicycle'],
        'C': ['cat', 'car', 'chair', 'cloud', 'computer', 'camera', 'cake', 'castle', 'circle', 'candle'],
        'D': ['dog', 'door', 'desk', 'drum', 'diamond', 'dragon', 'dolphin', 'donut', 'dinosaur', 'duck'],
        'E': ['egg', 'elephant', 'eye', 'ear', 'earth', 'eagle', 'engine', 'envelope', 'eraser', 'elevator'],
        'F': ['fish', 'flower', 'fork', 'fire', 'flag', 'fan', 'frog', 'fruit', 'falcon', 'feather'],
        'G': ['guitar', 'game', 'glass', 'gold', 'grape', 'green', 'gate', 'goat', 'gorilla', 'galaxy'],
        'H': ['hat', 'hand', 'house', 'horse', 'hammer', 'heart', 'honey', 'hedgehog', 'hornet', 'helicopter'],
        'I': ['ice', 'igloo', 'insect', 'island', 'iron', 'ink', 'instrument', 'internet', 'invoice', 'ivory'],
        'J': ['jam', 'jelly', 'jacket', 'jungle', 'jet', 'jewel', 'juice', 'journey', 'journal', 'jigsaw'],
        'K': ['key', 'kite', 'king', 'kitchen', 'knife', 'kangaroo', 'kayak', 'kiwi', 'kernel', 'knuckle'],
        'L': ['lion', 'lamp', 'leaf', 'ladder', 'lemon', 'laptop', 'lake', 'lollipop', 'lantern', 'llama'],
        'M': ['moon', 'mouse', 'milk', 'mountain', 'monkey', 'music', 'mango', 'mirror', 'mask', 'magnet'],
        'N': ['nest', 'nose', 'night', 'necklace', 'needle', 'net', 'notebook', 'napkin', 'noodle', 'nail'],
        'O': ['orange', 'ocean', 'owl', 'oil', 'onion', 'octopus', 'olive', 'orchid', 'orbit', 'ostrich'],
        'P': ['panda', 'phone', 'pizza', 'pen', 'paper', 'pear', 'park', 'peacock', 'piano', 'pillow'],
        'Q': ['queen', 'quail', 'quartz', 'question', 'quarter', 'quilt', 'quill', 'quiche', 'quiver', 'quiz'],
        'R': ['rain', 'rabbit', 'ring', 'radio', 'river', 'rocket', 'robot', 'rose', 'raccoon', 'reindeer'],
        'S': ['sun', 'snake', 'star', 'ship', 'sock', 'snow', 'spoon', 'strawberry', 'squirrel', 'scissors'],
        'T': ['tree', 'tiger', 'table', 'train', 'tooth', 'telephone', 'tomato', 'turtle', 'tunnel', 'trophy'],
        'U': ['umbrella', 'unicorn', 'unicycle', 'utensil', 'uniform', 'upstairs', 'underwear', 'ulcer', 'udder', 'urologist'],
        'V': ['violin', 'valley', 'vase', 'vegetable', 'vulture', 'video', 'village', 'volcano', 'vest', 'viewer'],
        'W': ['water', 'whale', 'window', 'watch', 'worm', 'wolf', 'wedding', 'wallet', 'windmill', 'wreath'],
        'X': ['xylophone', 'xenon', 'xerography', 'xylem', 'xyster', 'xenolith', 'xylocarp', 'xanthan', 'xiphias', 'xylotomy'],
        'Y': ['yellow', 'yogurt', 'yarn', 'yard', 'yacht', 'yam', 'yawn', 'year', 'yodel', 'yew'],
        'Z': ['zebra', 'zipper', 'zoo', 'zombie', 'zucchini', 'zealot', 'zenith', 'zigzag', 'zodiac', 'zephyr']
    }
    
    # Build complete word list
    all_words = set(words)
    for words_list in extended_words.values():
        all_words.update(words_list)
    
    last_letter_upper = last_letter.upper()
    
    # Find a word starting with last_letter
    candidates = []
    for word in all_words:
        if word.upper().startswith(last_letter_upper) and word not in used_words_set:
            candidates.append(word)
    
    if candidates:
        # Return random word from candidates
        import random
        return random.choice(candidates)
    
    return None

# ==================== OWNER FILTER ====================

def owner_only():
    """Filter to only allow owner"""
    async def func(flt, client: Client, message: Message):
        return message.from_user and message.from_user.id == flt.owner_id
    
    return filters.create(func, owner_id=OWNER_ID)

# ==================== TAG SYSTEM ====================

@app.on_message(filters.command("tagall") & owner_only())
async def tag_all(client: Client, message: Message):
    """Tag all real users in the chat"""
    chat_id = message.chat.id
    
    try:
        await message.edit("🔄 Fetching members...")
    except:
        await message.reply("🔄 Fetching members...")
    
    members = await get_chat_members(chat_id, "real_no_admins")
    
    if not members:
        await message.edit("❌ No members found.")
        return
    
    mentions = []
    batch_size = 10
    
    for i in range(0, len(members), batch_size):
        batch = members[i:i + batch_size]
        batch_mentions = []
        
        for user in batch:
            try:
                mention = await mention_user(user)
                batch_mentions.append(mention)
            except:
                continue
        
        if batch_mentions:
            mentions.append(", ".join(batch_mentions))
        
        if (i + batch_size) % 50 == 0:
            try:
                await message.edit(f"📝 Processing... {i + batch_size}/{len(members)}")
            except:
                pass
    
    try:
        await message.edit(f"👥 Total members: {len(members)}\n\n" + "\n\n".join(mentions))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.edit(f"👥 Total members: {len(members)}\n\n" + "\n\n".join(mentions))

@app.on_message(filters.command("tagadmins") & owner_only())
async def tag_admins(client: Client, message: Message):
    """Tag all admins in the chat"""
    chat_id = message.chat.id
    
    try:
        await message.edit("🔄 Fetching admins...")
    except:
        await message.reply("🔄 Fetching admins...")
    
    members = await get_chat_members(chat_id, "admins")
    
    if not members:
        await message.edit("❌ No admins found.")
        return
    
    mentions = []
    for user in members:
        try:
            mention = await mention_user(user)
            mentions.append(mention)
        except:
            continue
    
    text = "👮 Admins:\n\n" + ", ".join(mentions)
    
    try:
        await message.edit(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.edit(text)

# ==================== WELCOME SYSTEM ====================

@app.on_message(filters.new_chat_members)
async def welcome(client: Client, message: Message):
    """Auto welcome new members"""
    for new_user in message.new_chat_members:
        if new_user.is_bot:
            continue
        
        try:
            mention = await mention_user(new_user)
            await message.reply(f"👋 Welcome {mention} to the group!")
        except Exception as e:
            print(f"Welcome error: {e}")

# ==================== MODERATION ====================

async def ban_user(chat_id: int, user_id: int, message: Message):
    """Ban a user"""
    try:
        await app.ban_chat_member(chat_id, user_id)
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await ban_user(chat_id, user_id, message)
    except Exception as e:
        await message.reply(f"❌ Error banning user: {e}")
        return False

async def unban_user(chat_id: int, user_id: int, message: Message):
    """Unban a user"""
    try:
        await app.unban_chat_member(chat_id, user_id)
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await unban_user(chat_id, user_id, message)
    except Exception as e:
        await message.reply(f"❌ Error unbanning user: {e}")
        return False

async def mute_user(chat_id: int, user_id: int, duration: int, message: Message):
    """Mute a user"""
    try:
        await app.restrict_chat_member(
            chat_id, 
            user_id, 
            permissions=ChatMember(
                status=enums.ChatMemberStatus.RESTRICTED,
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            ),
            until_date=duration
        )
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await mute_user(chat_id, user_id, duration, message)
    except Exception as e:
        await message.reply(f"❌ Error muting user: {e}")
        return False

async def unmute_user(chat_id: int, user_id: int, message: Message):
    """Unmute a user"""
    try:
        await app.unban_chat_member(chat_id, user_id)
        # Re-apply default permissions
        await app.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatMember(
                status=enums.ChatMemberStatus.MEMBER,
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await unmute_user(chat_id, user_id, message)
    except Exception as e:
        await message.reply(f"❌ Error unmuting user: {e}")
        return False

@app.on_message(filters.command("ban") & owner_only())
async def ban_cmd(client: Client, message: Message):
    """Ban a user"""
    chat_id = message.chat.id
    user = await get_user_from_message(message)
    
    if not user:
        await message.reply("❌ Reply to a user or provide user_id/username")
        return
    
    if not await can_modify(chat_id, user.id):
        await message.reply("❌ Cannot ban this user")
        return
    
    if await ban_user(chat_id, user.id, message):
        mention = await mention_user(user)
        await message.reply(f"🔨 Banned {mention}")

@app.on_message(filters.command("unban") & owner_only())
async def unban_cmd(client: Client, message: Message):
    """Unban a user"""
    chat_id = message.chat.id
    user = await get_user_from_message(message)
    
    if not user:
        await message.reply("❌ Reply to a user or provide user_id/username")
        return
    
    if await unban_user(chat_id, user.id, message):
        mention = await mention_user(user)
        await message.reply(f"✅ Unbanned {mention}")

@app.on_message(filters.command("mute") & owner_only())
async def mute_cmd(client: Client, message: Message):
    """Mute a user"""
    chat_id = message.chat.id
    user = await get_user_from_message(message)
    
    if not user:
        await message.reply("❌ Reply to a user or provide user_id/username")
        return
    
    if not await can_modify(chat_id, user.id):
        await message.reply("❌ Cannot mute this user")
        return
    
    # Mute for 30 days
    duration = int(time.time()) + (30 * 24 * 60 * 60)
    
    if await mute_user(chat_id, user.id, duration, message):
        mention = await mention_user(user)
        await message.reply(f"🔇 Muted {mention} for 30 days")

@app.on_message(filters.command("unmute") & owner_only())
async def unmute_cmd(client: Client, message: Message):
    """Unmute a user"""
    chat_id = message.chat.id
    user = await get_user_from_message(message)
    
    if not user:
        await message.reply("❌ Reply to a user or provide user_id/username")
        return
    
    if await unmute_user(chat_id, user.id, message):
        mention = await mention_user(user)
        await message.reply(f"🔊 Unmuted {mention}")

@app.on_message(filters.command("banall") & owner_only())
async def ban_all(client: Client, message: Message):
    """Ban all real users (except owner and admins)"""
    chat_id = message.chat.id
    
    try:
        await message.edit("🔄 Banning all users...")
    except:
        await message.reply("🔄 Banning all users...")
    
    members = await get_chat_members(chat_id, "real")
    banned = 0
    
    for user in members:
        if user.id == OWNER_ID:
            continue
        if await is_admin(chat_id, user.id):
            continue
        
        if await ban_user(chat_id, user.id, message):
            banned += 1
        
        # Small delay to avoid floods
        await asyncio.sleep(0.5)
    
    await message.edit(f"🔨 Banned {banned} users")

@app.on_message(filters.command("unbanall") & owner_only())
async def unban_all(client: Client, message: Message):
    """Unban all users"""
    chat_id = message.chat.id
    
    try:
        await message.edit("🔄 Unbanning all users...")
    except:
        await message.reply("🔄 Unbanning all users...")
    
    try:
        await app.unban_chat_member(chat_id, message.from_user.id)
    except:
        pass
    
    # Get banned members
    unbanned = 0
    try:
        async for member in app.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await app.unban_chat_member(chat_id, member.user.id)
                unbanned += 1
            except:
                continue
            await asyncio.sleep(0.3)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    
    await message.edit(f"✅ Unbanned {unbanned} users")

# ==================== WORD CHAIN ====================

@app.on_message(filters.command("wcstart") & owner_only())
async def wc_start(client: Client, message: Message):
    """Enable word chain in this chat"""
    chat_id = message.chat.id
    word_chain_enabled[chat_id] = True
    
    # Initialize storage
    if chat_id not in used_words:
        used_words[chat_id] = set()
    
    await message.reply("✅ Word chain enabled with @on9wordchainbot!")

@app.on_message(filters.command("wcstop") & owner_only())
async def wc_stop(client: Client, message: Message):
    """Disable word chain in this chat"""
    chat_id = message.chat.id
    word_chain_enabled[chat_id] = False
    await message.reply("⛔ Word chain disabled")

@app.on_message()
async def word_chain_listener(client: Client, message: Message):
    """Listen for @on9wordchainbot messages and respond"""
    chat_id = message.chat.id
    
    # Check if word chain is enabled for this chat
    if not word_chain_enabled.get(chat_id, False):
        return
    
    # Check if message is from @on9wordchainbot
    if not message.from_user or message.from_user.username != "on9wordchainbot":
        return
    
    text = message.text or message.caption
    if not text:
        return
    
    # Parse the word from the bot's message
    # Bot typically sends something like "Your word is: X" or "The word was: X"
    word_match = re.search(r'[Tt]he (?:next |last )?word (?:is|w(?:as|ill be))[:\s]+(\w+)', text)
    if not word_match:
        # Try alternative patterns
        word_match = re.search(r'["\']?(\w+)["\']?\s*$', text)
    
    if not word_match:
        return
    
    current_word = word_match.group(1).lower()
    
    # Initialize storage if needed
    if chat_id not in used_words:
        used_words[chat_id] = set()
    
    # Store the word from bot
    used_words[chat_id].add(current_word.lower())
    last_word_by_bot[chat_id] = current_word.lower()
    
    # Get last letter and find next word
    last_letter = extract_last_letter(current_word)
    
    if not last_letter:
        return
    
    # Find a valid next word
    next_word = find_next_word(last_letter, used_words[chat_id], chat_id)
    
    if not next_word:
        # Reset used words if stuck
        used_words[chat_id] = set()
        next_word = find_next_word(last_letter, set(), chat_id)
    
    if next_word:
        # Add human-like delay (2-5 seconds)
        import random
        delay = random.uniform(2, 5)
        await asyncio.sleep(delay)
        
        # Mark as used
        used_words[chat_id].add(next_word.lower())
        
        # Send the word
        try:
            await message.reply(next_word)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply(next_word)

# ==================== UTILITY COMMANDS ====================

@app.on_message(filters.command("ping") & owner_only())
async def ping(client: Client, message: Message):
    """Ping command"""
    start = time.time()
    await message.edit("🏓 Pong!")
    end = time.time()
    await message.edit(f"🏓 Pong! `{round((end - start) * 1000)}ms`")

@app.on_message(filters.command("status") & owner_only())
async def status(client: Client, message: Message):
    """Check bot status"""
    chat_id = message.chat.id
    wc_enabled = word_chain_enabled.get(chat_id, False)
    words_used = len(used_words.get(chat_id, set()))
    
    status_text = f"""
🤖 Bot Status

👥 Members: {len(await get_chat_members(chat_id, 'all'))}
🔗 Word Chain: {'✅ Enabled' if wc_enabled else '❌ Disabled'}
📝 Words Used: {words_used}
"""
    
    await message.edit(status_text)

# ==================== RUN ====================

if __name__ == "__main__":
    print("🤖 Starting Userbot...")
    print(f"👤 Owner ID: {OWNER_ID}")
    app.run()
