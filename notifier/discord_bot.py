#!/usr/bin/env python3
"""
notifier/discord_bot.py

Location:
    notifier/discord_bot.py

Purpose:
    Discord bot that lets you manage notifier/tournament_list.txt from
    Discord (including from your phone) instead of SSHing into the server.

    Slash commands (guild-scoped to DISCORD_GUILD_ID):
        /track <tournament>     - add a tournament to tournament_list.txt
        /untrack <tournament>   - remove a tournament from tournament_list.txt
        /tracked [count]        - show the most recently tracked tournaments
        /tracked-all            - show every tracked tournament
        /tournaments [query]    - browse/search tournaments known from the DB export
        /tournaments-all        - show every known tournament
        /refresh                - re-run export_tournaments.py immediately
        /help                   - list all commands
"""

import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands

# Make core/ importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, PROJECT_ROOT  # noqa: E402

NOTIFIER_DIR = Path(__file__).resolve().parent
TOURNAMENT_LIST_PATH = NOTIFIER_DIR / "tournament_list.txt"
ALL_TOURNAMENTS_PATH = NOTIFIER_DIR / "all_tournaments.txt"
EXPORT_SCRIPT_PATH = NOTIFIER_DIR / "export_tournaments.py"
LOG_PATH = PROJECT_ROOT / "logs" / "discord_bot.log"

MAX_AUTOCOMPLETE_CHOICES = 25
MAX_MESSAGE_LEN = 1900
DEFAULT_RECENT_COUNT = 10
MAX_SEARCH_RESULTS = 30


def log_line(message: str) -> None:
    """Append one timestamped line to the bot's log file."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{datetime.now()}\t{message}\n")


def load_lines(path: Path) -> list[str]:
    """Read a text file into a list of stripped, non-empty lines, in order."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def save_lines(path: Path, lines: list[str]) -> None:
    """Atomically write lines back to a text file, one per line."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as file:
        for line in lines:
            file.write(line + "\n")
    os.replace(tmp_path, path)


def find_case_insensitive(name: str, candidates: list[str]) -> str | None:
    """Return the candidate that matches name case-insensitively, if any."""
    lowered = name.strip().lower()
    for candidate in candidates:
        if candidate.lower() == lowered:
            return candidate
    return None


def in_correct_guild(interaction: discord.Interaction) -> bool:
    """Check the interaction came from the configured guild."""
    return bool(DISCORD_GUILD_ID) and interaction.guild_id == int(DISCORD_GUILD_ID)


def format_numbered(names: list[str], start: int = 1) -> str:
    """Format names as a numbered, newline-separated list."""
    return "\n".join(f"{i}. {name}" for i, name in enumerate(names, start=start))


async def send_full_list(
    interaction: discord.Interaction, names: list[str], filename: str, empty_message: str
) -> None:
    """Reply with every name, inline if short enough, otherwise as a file attachment."""
    if not names:
        await interaction.response.send_message(empty_message, ephemeral=True)
        return

    body = format_numbered(names)
    if len(body) <= MAX_MESSAGE_LEN:
        await interaction.response.send_message(f"```\n{body}\n```", ephemeral=True)
    else:
        file = discord.File(io.BytesIO(body.encode("utf-8")), filename=filename)
        await interaction.response.send_message(f"{len(names)} total:", file=file, ephemeral=True)


class TournamentBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=int(DISCORD_GUILD_ID))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log_line(f"Synced commands to guild {DISCORD_GUILD_ID}")


client = TournamentBot()


async def track_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    all_names = load_lines(ALL_TOURNAMENTS_PATH)
    current_lower = current.lower()
    matches = [name for name in all_names if current_lower in name.lower()]
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in matches[:MAX_AUTOCOMPLETE_CHOICES]
    ]


async def untrack_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    tracked_names = load_lines(TOURNAMENT_LIST_PATH)
    current_lower = current.lower()
    matches = [name for name in tracked_names if current_lower in name.lower()]
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in matches[:MAX_AUTOCOMPLETE_CHOICES]
    ]


@client.tree.command(description="Add a tournament to the notifier watch list")
@app_commands.describe(tournament="Tournament name (autocompletes from known tournaments)")
@app_commands.autocomplete(tournament=track_autocomplete)
async def track(interaction: discord.Interaction, tournament: str):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    all_names = load_lines(ALL_TOURNAMENTS_PATH)
    tracked = load_lines(TOURNAMENT_LIST_PATH)

    canonical = find_case_insensitive(tournament, all_names)
    name_to_add = canonical or tournament.strip()

    if find_case_insensitive(name_to_add, tracked):
        await interaction.response.send_message(
            f"Already tracking **{name_to_add}**.", ephemeral=True
        )
        return

    tracked.append(name_to_add)
    save_lines(TOURNAMENT_LIST_PATH, tracked)
    log_line(f"TRACK added: {name_to_add}")

    note = "" if canonical else "\n_(not found in known tournaments export — added as typed, double-check spelling)_"
    await interaction.response.send_message(
        f"Now tracking **{name_to_add}**. ({len(tracked)} total){note}", ephemeral=True
    )


@client.tree.command(description="Remove a tournament from the notifier watch list")
@app_commands.describe(tournament="Tournament name to stop tracking")
@app_commands.autocomplete(tournament=untrack_autocomplete)
async def untrack(interaction: discord.Interaction, tournament: str):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    tracked = load_lines(TOURNAMENT_LIST_PATH)
    match = find_case_insensitive(tournament, tracked)

    if not match:
        await interaction.response.send_message(
            f"**{tournament}** isn't currently tracked.", ephemeral=True
        )
        return

    tracked.remove(match)
    save_lines(TOURNAMENT_LIST_PATH, tracked)
    log_line(f"UNTRACK removed: {match}")

    await interaction.response.send_message(
        f"Stopped tracking **{match}**. ({len(tracked)} total)", ephemeral=True
    )


@client.tree.command(description="Show the most recently tracked tournaments")
@app_commands.describe(count="How many to show, most recent first (default 10, max 50)")
async def tracked(interaction: discord.Interaction, count: app_commands.Range[int, 1, 50] = DEFAULT_RECENT_COUNT):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    names = load_lines(TOURNAMENT_LIST_PATH)
    if not names:
        await interaction.response.send_message("Nothing is tracked yet.", ephemeral=True)
        return

    recent = list(reversed(names[-count:]))
    body = format_numbered(recent)
    footer = (
        f"\nShowing {len(recent)} most recent of {len(names)} total. Use /tracked-all for the full list."
        if len(recent) < len(names)
        else ""
    )

    if len(body) + len(footer) <= MAX_MESSAGE_LEN:
        await interaction.response.send_message(f"```\n{body}\n```{footer}", ephemeral=True)
    else:
        file = discord.File(io.BytesIO(body.encode("utf-8")), filename="recent_tracked.txt")
        await interaction.response.send_message(
            f"{len(recent)} most recently tracked:", file=file, ephemeral=True
        )


@client.tree.command(name="tracked-all", description="Show every tracked tournament")
async def tracked_all(interaction: discord.Interaction):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    names = load_lines(TOURNAMENT_LIST_PATH)
    await send_full_list(interaction, names, "tracked_tournaments.txt", "Nothing is tracked yet.")


@client.tree.command(description="Browse tournaments known from the database export (search or see most recent)")
@app_commands.describe(query="Optional text filter; leave blank to see the most recently active tournaments")
async def tournaments(interaction: discord.Interaction, query: str | None = None):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    all_names = load_lines(ALL_TOURNAMENTS_PATH)
    if not all_names:
        await interaction.response.send_message(
            "No tournaments exported yet — try /refresh first.", ephemeral=True
        )
        return

    if query:
        query_lower = query.lower()
        matches = [name for name in all_names if query_lower in name.lower()]
        if not matches:
            await interaction.response.send_message(f"No tournaments match '{query}'.", ephemeral=True)
            return

        shown = matches[:MAX_SEARCH_RESULTS]
        body = format_numbered(shown)
        footer = (
            f"\nShowing {len(shown)} of {len(matches)} matches for '{query}'."
            if len(shown) < len(matches)
            else ""
        )
        await interaction.response.send_message(f"```\n{body}\n```{footer}", ephemeral=True)
        return

    recent = list(reversed(all_names[-DEFAULT_RECENT_COUNT:]))
    body = format_numbered(recent)
    footer = (
        f"\nMost recently active {len(recent)} of {len(all_names)} known tournaments. "
        f"Use /tournaments <text> to search, or /tournaments-all for the full list."
    )
    await interaction.response.send_message(f"```\n{body}\n```{footer}", ephemeral=True)


@client.tree.command(name="tournaments-all", description="Show every tournament known from the database export")
async def tournaments_all(interaction: discord.Interaction):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    all_names = load_lines(ALL_TOURNAMENTS_PATH)
    await send_full_list(
        interaction, all_names, "all_tournaments.txt", "No tournaments exported yet — try /refresh first."
    )


@client.tree.command(description="Re-run export_tournaments.py now instead of waiting for cron")
async def refresh(interaction: discord.Interaction):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        result = subprocess.run(
            [sys.executable, str(EXPORT_SCRIPT_PATH)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (result.stdout or result.stderr or "(no output)").strip()
        log_line(f"REFRESH: {output}")
        await interaction.followup.send(f"```\n{output}\n```", ephemeral=True)
    except Exception as exc:
        log_line(f"ERROR refresh failed: {exc}")
        await interaction.followup.send(f"Refresh failed: {exc}", ephemeral=True)


@client.tree.command(name="help", description="List all available commands")
async def help_command(interaction: discord.Interaction):
    if not in_correct_guild(interaction):
        await interaction.response.send_message("Not authorized here.", ephemeral=True)
        return

    lines = []
    for command in client.tree.get_commands():
        params = "".join(
            f" <{param.name}>" if param.required else f" [{param.name}]"
            for param in command.parameters
        )
        lines.append(f"/{command.name}{params} — {command.description}")

    body = "\n".join(lines)
    await interaction.response.send_message(f"```\n{body}\n```", ephemeral=True)


@client.event
async def on_ready():
    log_line(f"Logged in as {client.user} (id={client.user.id})")


def main():
    if not DISCORD_BOT_TOKEN:
        print("[ERROR] DISCORD_BOT_TOKEN is not set in .env")
        return
    if not DISCORD_GUILD_ID:
        print("[ERROR] DISCORD_GUILD_ID is not set in .env")
        return

    client.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
