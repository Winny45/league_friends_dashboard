"""Which class each champion belongs to.

Data Dragon only has six broad tags (Fighter, Mage, Tank...), and "Tank"
covers both Leona and Braum, who do opposite jobs. Riot's design team uses
thirteen finer subclasses, but does not publish them as data, so they are
kept here by hand.

This is a judgement, not a fact from the API. Where Riot lists a champion
under one class but they are played as another in the role this group plays
them (Pyke is filed as an assassin and played as a hook support), the entry
follows how they are played, because the point of a class here is to compare
like with like. A champion missing from the table falls back to its first
Data Dragon tag, so a new release shows up as something rather than nothing.
"""

import re

CLASSES = [
    "Enchanter", "Catcher", "Warden", "Vanguard", "Juggernaut", "Diver",
    "Skirmisher", "Assassin", "Burst mage", "Battlemage", "Artillery",
    "Marksman", "Specialist",
]

_BY_CLASS = {
    "Enchanter": "Janna Karma Lulu Milio Nami Renata RenataGlasc Seraphine Sona Soraka Yuumi Taric",
    "Catcher": "Bard Blitzcrank Ivern Morgana Pyke Rakan Thresh Zyra Neeko",
    "Warden": "Braum Galio KSante Poppy Shen TahmKench",
    "Vanguard": "Alistar Amumu Gragas Leona Malphite Maokai Nautilus Nunu NunuWillump Ornn Rammus Rell "
                "Sejuani Sion Skarner Zac",
    "Juggernaut": "Aatrox Darius DrMundo Garen Illaoi Mordekaiser Nasus Sett Shyvana Trundle Udyr Urgot "
                  "Volibear Yorick Zaahen",
    "Diver": "Ambessa Briar Camille Diana Elise Hecarim Irelia JarvanIV LeeSin Olaf Pantheon RekSai "
             "Renekton Vi Warwick Wukong MonkeyKing XinZhao",
    "Skirmisher": "Belveth Fiora Gwen Jax Kayn Kled Lillia MasterYi Nilah Riven Tryndamere Viego Yasuo Yone",
    "Assassin": "Akali Ekko Evelynn Fizz Kassadin Katarina Khazix Leblanc Naafiri Nidalee Nocturne Qiyana "
                "Rengar Shaco Talon Zed",
    "Burst mage": "Ahri Annie Aurora Brand Lissandra Lux Orianna Sylas Syndra TwistedFate Veigar Vex Zoe",
    "Battlemage": "Anivia AurelionSol Cassiopeia Karthus Malzahar Rumble Ryze Swain Taliyah Viktor Vladimir",
    "Artillery": "Hwei Jayce Mel Velkoz Xerath Ziggs",
    "Marksman": "Akshan Aphelios Ashe Caitlyn Corki Draven Ezreal Jhin Jinx Kaisa Kalista Kindred KogMaw "
                "Lucian MissFortune Samira Senna Sivir Smolder Tristana Twitch Varus Vayne Xayah Yunara Zeri",
    "Specialist": "Azir Chogath Fiddlesticks Gangplank Gnar Graves Heimerdinger Kayle Kennen Quinn Singed "
                  "Teemo Zilean",
}

_TAG_FALLBACK = {
    "Marksman": "Marksman", "Assassin": "Assassin", "Mage": "Burst mage",
    "Tank": "Vanguard", "Fighter": "Diver", "Support": "Enchanter",
}


def _norm(name):
    return re.sub(r"[^a-z]", "", str(name).lower())


_LOOKUP = {_norm(champ): cls for cls, names in _BY_CLASS.items() for champ in names.split()}


def champion_class(slug, tags=()):
    """The subclass for a champion slug or display name."""
    hit = _LOOKUP.get(_norm(slug))
    if hit:
        return hit
    for tag in tags or ():
        if tag in _TAG_FALLBACK:
            return _TAG_FALLBACK[tag]
    return "Specialist"
