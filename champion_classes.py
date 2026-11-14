"""Each champion's class and descriptive tags, as the League wiki has them.

Source: the League of Legends Wiki (wiki.leagueoflegends.com), its
Module:ChampionData, read on 2026-11-14. "class" is the wiki's "role" field
and "tags" is its "client_tags", which are the three words the game client
shows under a champion's name. The wiki is credited in the page footer.

Kept by hand, in this one file. When a champion is released or reworked, add
or change its line in _TABLE; nothing else needs touching. A champion that is
not listed yet still gets a class, guessed from Data Dragon's much coarser
tags, so a new release never breaks a build: it just sits in a rough group
until somebody adds the line.

A champion with two classes on the wiki is filed under the first, which is
the one the wiki treats as primary. Both are kept and shown.

Five entries have no tags because the wiki has none for them (Evelynn,
Katarina, Renata Glasc, Sona) or lists only a damage type. They are left
empty rather than filled in from memory.
"""

# The thirteen classes, in the order the pages list them, under the wiki's
# own names except "Burst", which is written "Burst mage" so it cannot be
# read as the tag of the same name.
CLASSES = ["Enchanter", "Catcher", "Warden", "Vanguard", "Juggernaut", "Diver", "Skirmisher",
           "Assassin", "Burst mage", "Battlemage", "Artillery", "Marksman", "Specialist"]

# The wiki's parent classes, used to group the champion grid.
FAMILIES = [
    ("Controller", ["Enchanter", "Catcher"]),
    ("Fighter", ["Juggernaut", "Diver"]),
    ("Mage", ["Burst mage", "Battlemage", "Artillery"]),
    ("Marksman", ["Marksman"]),
    ("Slayer", ["Assassin", "Skirmisher"]),
    ("Tank", ["Vanguard", "Warden"]),
    ("Specialist", ["Specialist"]),
]
FAMILY_OF = {cls: family for family, members in FAMILIES for cls in members}

# Every tag the wiki uses. Only some can be measured from a match; scoring.py
# says which.
TAGS = ["Ally Protection", "AoE", "Auto-attack", "Battlecaster", "Burst", "Crowd Control",
        "Damage-over-Time", "Dive", "Duelist", "Durable", "Hypercarry", "Initiator", "Long Range",
        "Magic", "Mixed", "Mobile", "Physical", "Self Healing", "Shapeshift", "Stealth",
        "Summon", "Sustained Damage"]

# Data Dragon id | class[, second class] | tag, tag, tag
_TABLE = """
Aatrox|Juggernaut|Sustained Damage,Self Healing,Physical
Ahri|Burst|Mobile,Burst,Magic
Akali|Assassin|Mobile,Burst,Magic
Akshan|Marksman,Assassin|Mobile,Stealth,Physical
Alistar|Vanguard|Crowd Control,Initiator,Magic
Ambessa|Diver,Skirmisher|Mobile,Dive,Physical
Amumu|Vanguard|Crowd Control,Initiator,Magic
Anivia|Battlemage|AoE,Crowd Control,Magic
Annie|Burst|Summon,Burst,Magic
Aphelios|Marksman|Hypercarry,Auto-attack,Physical
Ashe|Marksman|Auto-attack,Crowd Control,Physical
AurelionSol|Battlemage|Hypercarry,AoE,Magic
Aurora|Burst,Assassin|Burst,Stealth,Magic
Azir|Specialist|Hypercarry,Auto-attack,Magic
Bard|Catcher|Crowd Control,Mobile,Magic
Belveth|Skirmisher|Auto-attack,Mobile,Physical
Blitzcrank|Catcher|Initiator,Crowd Control,Magic
Brand|Burst|Damage-over-Time,AoE,Magic
Braum|Warden|Durable,Crowd Control,Magic
Briar|Diver|Self Healing,Dive,Physical
Caitlyn|Marksman|Auto-attack,Burst,Physical
Camille|Diver|Dive,Duelist,Physical
Cassiopeia|Battlemage|Crowd Control,Sustained Damage,Magic
Chogath|Specialist|Durable,Crowd Control,Magic
Corki|Marksman|Auto-attack,AoE,Physical
Darius|Juggernaut|Duelist,Self Healing,Physical
Diana|Assassin,Diver|Burst,Dive,Magic
DrMundo|Juggernaut|Durable,Self Healing,Mixed
Draven|Marksman|Auto-attack,Burst,Physical
Ekko|Assassin|Burst,Mobile,Magic
Elise|Diver|Shapeshift,Burst,Magic
Evelynn|Assassin|
Ezreal|Marksman|Long Range,Mobile,Physical
Fiddlesticks|Specialist|Self Healing,AoE,Magic
Fiora|Skirmisher|Duelist,Mobile,Physical
Fizz|Assassin|Burst,Mobile,Magic
Galio|Warden|Battlecaster,Crowd Control,Magic
Gangplank|Specialist|AoE,Burst,Physical
Garen|Juggernaut|Durable,Sustained Damage,Physical
Gnar|Specialist|Shapeshift,Crowd Control,Physical
Gragas|Vanguard|Burst,Crowd Control,Magic
Graves|Specialist|Burst,Auto-attack,Physical
Gwen|Skirmisher|Sustained Damage,Duelist,Magic
Hecarim|Diver|Mobile,Dive,Physical
Heimerdinger|Specialist|Summon,Sustained Damage,Magic
Hwei|Artillery|AoE,Long Range,Magic
Illaoi|Juggernaut|Self Healing,Duelist,Physical
Irelia|Diver|Mobile,Duelist,Physical
Ivern|Catcher|Summon,Ally Protection,Magic
Janna|Enchanter|Crowd Control,Ally Protection,Magic
JarvanIV|Diver|Dive,Crowd Control,Physical
Jax|Skirmisher|Duelist,Auto-attack,Physical
Jayce|Artillery|Shapeshift,Long Range,Physical
Jhin|Marksman,Catcher|Long Range,Burst,Physical
Jinx|Marksman|Auto-attack,Hypercarry,Physical
KSante|Warden,Skirmisher|Durable,Duelist,Physical
Kaisa|Marksman|Dive,Auto-attack,Physical
Kalista|Marksman|Mobile,Auto-attack,Physical
Karma|Burst,Enchanter|Ally Protection,AoE,Magic
Karthus|Battlemage|AoE,Sustained Damage,Magic
Kassadin|Assassin|Hypercarry,Mobile,Magic
Katarina|Assassin|
Kayle|Specialist|Hypercarry,Auto-attack,Magic
Kayn|Skirmisher|Mobile,Dive,Physical
Kennen|Specialist|Burst,AoE,Magic
Khazix|Assassin|Burst,Stealth,Physical
Kindred|Marksman|Auto-attack,Mobile,Physical
Kled|Skirmisher|Dive,Duelist,Physical
KogMaw|Marksman|Hypercarry,Auto-attack,Mixed
Leblanc|Burst,Assassin|Burst,Mobile,Magic
LeeSin|Diver|Mobile,Duelist,Physical
Leona|Vanguard|Initiator,Crowd Control,Magic
Lillia|Skirmisher|Mobile,Damage-over-Time,Magic
Lissandra|Burst|Crowd Control,Burst,Magic
Locke|Assassin|Burst,Mobile,Magic
Lucian|Marksman|Mobile,Burst,Physical
Lulu|Enchanter|Ally Protection,Crowd Control,Magic
Lux|Burst,Artillery|Burst,Long Range,Magic
Malphite|Vanguard|Initiator,Crowd Control,Magic
Malzahar|Battlemage|Damage-over-Time,Summon,Magic
Maokai|Vanguard|Initiator,Crowd Control,Magic
MasterYi|Skirmisher|Auto-attack,Hypercarry,Physical
Mel|Artillery|Long Range,AoE,Magic
Milio|Enchanter|Ally Protection,AoE,Magic
MissFortune|Marksman|AoE,Burst,Physical
Mordekaiser|Juggernaut|Duelist,Sustained Damage,Magic
Morgana|Catcher|Crowd Control,Ally Protection,Magic
Naafiri|Assassin|Summon,Mobile,Physical
Nami|Enchanter|Ally Protection,Crowd Control,Magic
Nasus|Juggernaut|Durable,Hypercarry,Physical
Nautilus|Vanguard|Initiator,Crowd Control,Magic
Neeko|Burst,Catcher|AoE,Burst,Magic
Nidalee|Specialist|Shapeshift,Mobile,Magic
Nilah|Skirmisher|Auto-attack,AoE,Physical
Nocturne|Assassin|Dive,Duelist,Physical
Nunu|Vanguard|Initiator,Battlecaster,Magic
Olaf|Diver|Duelist,Self Healing,Physical
Orianna|Burst|AoE,Long Range,Magic
Ornn|Vanguard|Initiator,Crowd Control,Magic
Pantheon|Diver|Dive,Duelist,Physical
Poppy|Warden|Durable,Dive,Physical
Pyke|Assassin,Catcher|Mobile,Stealth,Physical
Qiyana|Assassin|Burst,Mobile,Physical
Quinn|Specialist|Mobile,Duelist,Physical
Rakan|Catcher|Mobile,Crowd Control,Magic
Rammus|Vanguard|Mobile,Crowd Control,Magic
RekSai|Diver|Mobile,Dive,Physical
Rell|Vanguard|Crowd Control,Initiator,Magic
Renata|Enchanter|
Renekton|Diver|Duelist,Durable,Physical
Rengar|Assassin,Diver|Stealth,Burst,Physical
Riven|Skirmisher|Mobile,Duelist,Physical
Rumble|Battlemage|Damage-over-Time,Battlecaster,Magic
Ryze|Battlemage|Battlecaster,Sustained Damage,Magic
Samira|Marksman|AoE,Dive,Physical
Sejuani|Vanguard|Crowd Control,Initiator,Magic
Senna|Marksman,Enchanter|Auto-attack,Ally Protection,Physical
Seraphine|Burst,Enchanter|AoE,Ally Protection,Magic
Sett|Juggernaut|Duelist,Durable,Physical
Shaco|Assassin|Stealth,Summon,Mixed
Shen|Warden|Ally Protection,Duelist,Mixed
Shyvana|Diver|Mixed
Singed|Specialist|Battlecaster,Damage-over-Time,Magic
Sion|Vanguard|Durable,Crowd Control,Physical
Sivir|Marksman|AoE,Auto-attack,Physical
Skarner|Vanguard,Juggernaut|Crowd Control,Initiator,Physical
Smolder|Marksman|Hypercarry,AoE,Physical
Sona|Enchanter|
Soraka|Enchanter|Ally Protection,Crowd Control,Magic
Swain|Battlemage|Battlecaster,Self Healing,Magic
Sylas|Burst,Skirmisher|Duelist,Battlecaster,Magic
Syndra|Burst|Burst,Long Range,Magic
TahmKench|Warden|Crowd Control,Ally Protection,Magic
Taliyah|Battlemage|Crowd Control,AoE,Magic
Talon|Assassin|Mobile,Burst,Physical
Taric|Enchanter,Warden|Durable,Ally Protection,Magic
Teemo|Specialist|Damage-over-Time,Stealth,Magic
Thresh|Catcher|Initiator,Ally Protection,Magic
Tristana|Marksman|Mobile,Auto-attack,Physical
Trundle|Juggernaut|Duelist,Self Healing,Physical
Tryndamere|Skirmisher|Duelist,Auto-attack,Physical
TwistedFate|Burst|Burst,Auto-attack,Magic
Twitch|Marksman|Hypercarry,Stealth,Physical
Udyr|Juggernaut|Auto-attack,Durable,Mixed
Urgot|Juggernaut|Duelist,Sustained Damage,Physical
Varus|Marksman,Artillery|Long Range,Auto-attack,Physical
Vayne|Marksman|Hypercarry,Stealth,Physical
Veigar|Burst|Hypercarry,Burst,Magic
Velkoz|Artillery|Long Range,AoE,Magic
Vex|Burst|Burst,Crowd Control,Magic
Vi|Diver|Dive,Auto-attack,Physical
Viego|Skirmisher|Shapeshift,Duelist,Physical
Viktor|Battlemage|Sustained Damage,AoE,Magic
Vladimir|Battlemage|Self Healing,Battlecaster,Magic
Volibear|Juggernaut|Duelist,Durable,Mixed
Warwick|Diver|Self Healing,Duelist,Mixed
MonkeyKing|Diver|Dive,AoE,Physical
Xayah|Marksman|AoE,Auto-attack,Physical
Xerath|Artillery|Long Range,AoE,Magic
XinZhao|Diver|Physical
Yasuo|Skirmisher|Duelist,Mobile,Physical
Yone|Assassin,Skirmisher|Mobile,Duelist,Physical
Yorick|Juggernaut|Summon,Duelist,Physical
Yunara|Marksman|Auto-attack,Sustained Damage,Physical
Yuumi|Enchanter|Ally Protection,AoE,Magic
Zaahen|Skirmisher|Physical
Zac|Vanguard|Initiator,Self Healing,Magic
Zed|Assassin|Burst,Mobile,Physical
Zeri|Marksman|Mobile,Burst,Physical
Ziggs|Artillery|Long Range,AoE,Magic
Zilean|Specialist|Crowd Control,Ally Protection,Magic
Zoe|Burst|Burst,Long Range,Magic
Zyra|Catcher|Summon,Crowd Control,Magic
"""


def _parse(table):
    out = {}
    for line in table.strip().splitlines():
        slug, classes, tags = line.split("|")
        cls = ["Burst mage" if c == "Burst" else c for c in classes.split(",")]
        tag = [t for t in tags.split(",") if t]
        assert all(c in CLASSES for c in cls), line
        assert all(t in TAGS for t in tag), line
        out[slug.lower()] = (cls, tag)
    return out


_BY_SLUG = _parse(_TABLE)

# Data Dragon's first tag, for a champion the table does not have yet.
_FALLBACK = {"Marksman": "Marksman", "Assassin": "Assassin", "Mage": "Burst mage",
             "Support": "Enchanter", "Tank": "Vanguard", "Fighter": "Diver"}


def champion_class(slug, ddragon_tags=None):
    """The primary class. `slug` is the id match-v5 calls championName, which
    is spelt a little differently from Data Dragon's for a few champions
    (FiddleSticks), so the lookup ignores case."""
    hit = _BY_SLUG.get(str(slug or "").lower())
    if hit:
        return hit[0][0]
    for tag in ddragon_tags or []:
        if tag in _FALLBACK:
            return _FALLBACK[tag]
    return "Specialist"


def champion_classes(slug, ddragon_tags=None):
    """Every class the wiki gives, primary first."""
    hit = _BY_SLUG.get(str(slug or "").lower())
    return list(hit[0]) if hit else [champion_class(slug, ddragon_tags)]


def champion_tags(slug):
    """The wiki's descriptive tags, or an empty list where it has none."""
    hit = _BY_SLUG.get(str(slug or "").lower())
    return list(hit[1]) if hit else []


def is_listed(slug):
    return str(slug or "").lower() in _BY_SLUG
