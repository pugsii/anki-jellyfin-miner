"""Swap the Jellyfin Miner's still screenshots on existing cards for animated clips of the same line.
Run with Anki closed (back up your collection first), through Anki's own Python:
    python3 tools/animate_existing.py "path/to/Anki2/User 1" path/to/Anki2/addons21 [--dry-run]
(Linux Flatpak: flatpak run --command=python3 net.ankiweb.Anki ..., with the files under ~/.var/app/net.ankiweb.Anki/data)
The old .jpg files stay in the media folder (Tools → Check Media lists them as unused)."""
import json, os, re, sys, tempfile
profile, addons = sys.argv[1], sys.argv[2]
dry = "--dry-run" in sys.argv
sys.path.insert(0, addons)
sys.modules["aqt"] = None  # the add-on's pipeline modules only, not its Anki side
from jellyfin_miner import jellyfin, media, subtitles
from jellyfin_miner.jellyfin import JAPANESE
from anki.collection import Collection

PIC = re.compile(r'src="(jfm_([0-9a-f]{8})_(\d+))\.jpg"')
cfg = json.load(open(os.path.join(addons, "jellyfin_miner", "meta.json")))["config"]
jf = jellyfin.Jellyfin(cfg["jellyfin"]["url"], cfg["jellyfin"]["api_key"])
uid = jf.user_id(cfg["jellyfin"]["user"])
ffmpeg = media.find_ffmpeg(cfg.get("ffmpeg_path", ""))

col = Collection(os.path.join(profile, "collection.anki2"))
try:
    notes = [col.get_note(nid) for nid in col.find_notes("jfm")]
    notes = [n for n in notes if any(PIC.search(f) for f in n.fields)]
    wanted = {}  # base name -> (episode id prefix, deciseconds)
    for note in notes:
        for f in note.fields:
            for base, prefix, ds in PIC.findall(f):
                wanted[base] = (prefix, int(ds))
    print(len(notes), "notes,", len(wanted), "pictures")
    prefixes = {p for p, _ in wanted.values()}
    eps = [i["Id"] for i in jf.get("/Items", userId=uid, Recursive="true", IncludeItemTypes="Episode", Fields="")["Items"]
           if i["Id"][:8] in prefixes]
    items = {i["Id"][:8]: i for i in jf.get("/Items", userId=uid, Ids=",".join(eps), Fields="MediaStreams,MediaSources")["Items"]}
    made, failed = {}, []
    work = tempfile.mkdtemp()
    for prefix in sorted(prefixes):
        item = items.get(prefix)
        subs = item and jf.subtitles(item, JAPANESE)
        cues = subtitles.parse(*subs) if subs else []
        for base, (p, ds) in sorted(wanted.items()):
            if p != prefix:
                continue
            cue = next((c for c in cues if int(c[0] * 10) == ds), None)
            if not cue:
                failed.append(f"{base}: {'episode not found' if not item else 'line not found in subtitles'}")
                continue
            out = os.path.join(work, base + ".webp")
            try:
                if not dry:
                    media.animated_clip(ffmpeg, jf.stream_url(item), jf.stream_headers(), cue[0], cue[1], out)
                    made[base] = col.media.add_file(out)
                else:
                    made[base] = base + ".webp"
                print(f"  {base}: {jellyfin.label(item)} {cue[2][:30]}")
            except Exception as e:
                failed.append(f"{base}: {e}")
    changed = []
    for note in notes:
        new = [PIC.sub(lambda m: f'src="{made[m.group(1)]}"' if m.group(1) in made else m.group(0), f) for f in note.fields]
        if new != note.fields:
            note.fields[:] = new
            changed.append(note)
    if not dry and changed:
        col.update_notes(changed)
    print(f"{len(made)} clips, {len(changed)} notes {'would change' if dry else 'updated'}; {len(failed)} failed")
    for f in failed:
        print("  FAILED", f)
finally:
    col.close()
