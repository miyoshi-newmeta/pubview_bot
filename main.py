import discord
from discord.ext import tasks
from riotwatcher import RiotWatcher, LolWatcher, ApiError
import os
import sqlite3
import datetime

# --- 設定項目 ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
RIOT_API_KEY = os.getenv('RIOT_API_KEY') 
DB_PATH = '/data/lol_bot.db'
NOTIFICATION_CHANNEL_ID = 1401719055643312219 # 通知用チャンネルID
RANK_ROLES = {
    "IRON": "LoL Iron(Solo/Duo)", "BRONZE": "LoL Bronze(Solo/Duo)", "SILVER": "LoL Silver(Solo/Duo)", 
    "GOLD": "LoL Gold(Solo/Duo)", "PLATINUM": "LoL Platinum(Solo/Duo)", "EMERALD": "LoL Emerald(Solo/Duo)", 
    "DIAMOND": "LoL Diamond(Solo/Duo)", "MASTER": "LoL Master(Solo/Duo)", 
    "GRANDMASTER": "LoL Grandmaster(Solo/Duo)", "CHALLENGER": "LoL Challenger(Solo/Duo)"
}
# ----------------

# --- データベースの初期設定 ---
def setup_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            discord_id INTEGER PRIMARY KEY,
            riot_puuid TEXT NOT NULL UNIQUE,
            game_name TEXT,
            tag_line TEXT,
            tier TEXT,
            rank TEXT,
            league_points INTEGER
        )
    ''')
    con.commit()
    con.close()
# -----------------------------

# --- Botの初期設定 ---
intents = discord.Intents.default()
intents.members = True
bot = discord.Bot(intents=intents)

riot_watcher = RiotWatcher(RIOT_API_KEY)
lol_watcher = LolWatcher(RIOT_API_KEY)

my_region_for_account = 'asia'
my_region_for_summoner = 'jp1'
# -----------------------------

# --- ヘルパー関数 ---
def get_rank_by_puuid(puuid: str, region: str):
    try:
        ranked_stats = lol_watcher.league.by_puuid(region, puuid)
        for queue in ranked_stats:
            if queue.get("queueType") == "RANKED_SOLO_5x5":
                return {"tier": queue.get("tier"), "rank": queue.get("rank"), "leaguePoints": queue.get("leaguePoints")}
        return None
    except ApiError as err:
        if err.response.status_code == 404: return None
        else:
            print(f"API Error in get_rank_by_puuid for {puuid}: {err}")
            raise

def rank_to_value(tier, rank, lp):
    tier_values = {"CHALLENGER": 9, "GRANDMASTER": 8, "MASTER": 7, "DIAMOND": 6, "EMERALD": 5, "PLATINUM": 4, "GOLD": 3, "SILVER": 2, "BRONZE": 1, "IRON": 0}
    rank_values = {"I": 4, "II": 3, "III": 2, "IV": 1}
    tier_val = tier_values.get(tier.upper(), 0) * 1000
    rank_val = rank_values.get(rank.upper(), 0) * 100
    return tier_val + rank_val + lp

# --- ランキング作成ロジックを共通関数化 ---
async def create_ranking_embed():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT discord_id, riot_puuid, game_name, tag_line FROM users")
    registered_users = cur.fetchall()
    con.close()

    if not registered_users:
        return None

    player_ranks = []
    for discord_id, puuid, game_name, tag_line in registered_users:
        rank_info = get_rank_by_puuid(puuid, my_region_for_summoner)
        if rank_info:
            player_ranks.append({
                "discord_id": discord_id, "game_name": game_name, "tag_line": tag_line,
                "tier": rank_info['tier'], "rank": rank_info['rank'], "lp": rank_info['leaguePoints'],
                "value": rank_to_value(rank_info['tier'], rank_info['rank'], rank_info['leaguePoints'])
            })
    
    sorted_ranks = sorted(player_ranks, key=lambda x: x['value'], reverse=True)

    embed = discord.Embed(title="🏆 ぱぶびゅ！内LoL(Solo/Duo)ランキング 🏆", description="現在登録されているメンバーのランクです。", color=discord.Color.gold())
    if not sorted_ranks:
        embed.description = "現在ランク情報を取得できるユーザーがいませんでした。"
        return embed

    for i, player in enumerate(sorted_ranks[:20]):
        try:
            user = await bot.fetch_user(player['discord_id'])
            display_name = user.display_name
        except discord.NotFound:
            display_name = f"ID: {player['discord_id']}"
        
        riot_id_full = f"{player['game_name']}#{player['tag_line']}"
        embed.add_field(name=f"{i+1}. {display_name} ({riot_id_full})", value=f"**{player['tier']} {player['rank']} / {player['lp']}LP**", inline=False)
    
    return embed

# --- イベント ---
@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    
    # ▼▼▼ 起動時にランキングを投稿する処理を追加 ▼▼▼
    print("--- Posting initial ranking on startup ---")
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        ranking_embed = await create_ranking_embed()
        if ranking_embed:
            await channel.send("【起動時ランキング速報】", embed=ranking_embed)
    
    check_ranks_periodically.start()

# --- コマンド ---
@bot.slash_command(name="register", description="あなたのRiot IDをボットに登録します。")
async def register(ctx, game_name: str, tag_line: str):
    await ctx.defer()
    try:
        account_info = riot_watcher.account.by_riot_id(my_region_for_account, game_name, tag_line)
        puuid = account_info['puuid']
        rank_info = get_rank_by_puuid(puuid, my_region_for_summoner)
        
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        if rank_info:
            cur.execute("INSERT OR REPLACE INTO users (discord_id, riot_puuid, game_name, tag_line, tier, rank, league_points) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                        (ctx.author.id, puuid, game_name, tag_line, rank_info['tier'], rank_info['rank'], rank_info['leaguePoints']))
        else:
            cur.execute("INSERT OR REPLACE INTO users (discord_id, riot_puuid, game_name, tag_line, tier, rank, league_points) VALUES (?, ?, ?, ?, NULL, NULL, NULL)", 
                        (ctx.author.id, puuid, game_name, tag_line))
        con.commit()
        con.close()
        await ctx.respond(f"Riot ID「{game_name}#{tag_line}」を登録しました！")
    except ApiError as err:
        if err.response.status_code == 404: await ctx.respond(f"Riot ID「{game_name}#{tag_line}」が見つかりませんでした。")
        else: await ctx.respond("Riot APIでエラーが発生しました。")
    except Exception as e:
        print(f"!!! An unexpected error occurred in 'register' command: {e}")
        await ctx.respond("登録中に予期せぬエラーが発生しました。")

@bot.slash_command(name="unregister", description="ボットからあなたの登録情報を削除します。")
async def unregister(ctx):
    await ctx.defer()
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("DELETE FROM users WHERE discord_id = ?", (ctx.author.id,))
        con.commit()
        if con.total_changes > 0: await ctx.respond("あなたの登録情報を削除しました。")
        else: await ctx.respond("あなたはまだ登録されていません。")
        con.close()
    except Exception as e:
        await ctx.respond("登録解除中に予期せぬエラーが発生しました。")

@bot.slash_command(name="ranking", description="サーバー内のLoLランクランキングを表示します。")
async def ranking(ctx):
    await ctx.defer()
    try:
        ranking_embed = await create_ranking_embed()
        if ranking_embed:
            await ctx.respond(embed=ranking_embed)
        else:
            await ctx.respond("まだ誰も登録されていないか、ランク情報を取得できるユーザーがいません。")
    except Exception as e:
        print(f"!!! An unexpected error occurred in 'ranking' command: {e}")
        await ctx.respond("ランキングの作成中にエラーが発生しました。")

# --- バックグラウンドタスク ---
jst = datetime.timezone(datetime.timedelta(hours=9))
@tasks.loop(time=datetime.time(hour=12, minute=0, tzinfo=jst))
async def check_ranks_periodically():
    print("--- Starting periodic rank check ---")
    
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        ranking_embed = await create_ranking_embed()
        if ranking_embed:
            await channel.send("【定期ランキング速報】", embed=ranking_embed)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT discord_id, riot_puuid, tier, rank, game_name, tag_line FROM users")
    registered_users = cur.fetchall()
    if not registered_users:
        con.close()
        return

    if not channel:
        print(f"Error: Notification channel with ID {NOTIFICATION_CHANNEL_ID} not found.")
        con.close()
        return

    for discord_id, puuid, old_tier, old_rank, game_name, tag_line in registered_users:
        try:
            new_rank_info = get_rank_by_puuid(puuid, my_region_for_summoner)
            guild = channel.guild
            member = await guild.fetch_member(discord_id)
            if not member: continue

            # --- ランク連動ロール処理 ---
            current_rank_tier = new_rank_info['tier'].upper() if new_rank_info else None
            role_names_to_remove = [discord.utils.get(guild.roles, name=role_name) for role_name in RANK_ROLES.values()]
            await member.remove_roles(*[role for role in role_names_to_remove if role is not None and role in member.roles])
            if current_rank_tier and current_rank_tier in RANK_ROLES:
                role_to_add = discord.utils.get(guild.roles, name=RANK_ROLES[current_rank_tier])
                if role_to_add: await member.add_roles(role_to_add)

            # --- ランクアップ通知処理 ---
            if new_rank_info and old_tier and old_rank:
                old_value = rank_to_value(old_tier, old_rank, 0)
                new_value = rank_to_value(new_rank_info['tier'], new_rank_info['rank'], 0)
                if new_value > old_value:
                    riot_id_full = f"{game_name}#{tag_line}"
                    await channel.send(f"🎉 **ランクアップ！** 🎉\nおめでとうございます、{member.mention}さん ({riot_id_full})！\n**{old_tier} {old_rank}** → **{new_rank_info['tier']} {new_rank_info['rank']}** に昇格しました！")

            # --- データベース更新 ---
            if new_rank_info:
                cur.execute("UPDATE users SET tier = ?, rank = ?, league_points = ? WHERE discord_id = ?",
                            (new_rank_info['tier'], new_rank_info['rank'], new_rank_info['leaguePoints'], discord_id))
            else:
                cur.execute("UPDATE users SET tier = NULL, rank = NULL, league_points = NULL WHERE discord_id = ?", (discord_id,))
        except discord.NotFound:
             print(f"User with ID {discord_id} not found in the server. Skipping.")
             continue
        except Exception as e:
            print(f"Error processing user {discord_id}: {e}")
            continue
            
    con.commit()
    con.close()
    print("--- Periodic rank check finished ---")

# --- Botの起動 ---
if __name__ == '__main__':
    setup_database()
    bot.run(DISCORD_TOKEN)
