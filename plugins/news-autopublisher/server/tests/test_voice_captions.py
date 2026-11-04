from newsautopublisher.models import Word
from newsautopublisher.video.captions import TimedScene, ass_color, ass_time, build_ass, chunk_words
from newsautopublisher.video.storyboard import Scene, Storyboard
from newsautopublisher.voice.elevenlabs import words_from_alignment
from newsautopublisher.voice.recorded import align_by_silences, map_to_script
from newsautopublisher.voice.text import estimate_words, split_sentences


def test_split_and_estimate():
    s = split_sentences("Bonjour à tous ! Voici le devlog. Bonne lecture…\nÀ bientôt")
    assert s == ["Bonjour à tous !", "Voici le devlog.", "Bonne lecture…", "À bientôt"]
    w = estimate_words("Voici le devlog.", 1.0, 2.0)
    assert [x.text for x in w] == ["Voici", "le", "devlog."]
    assert w[0].start == 1.0 and abs(w[-1].end - 2.0) < 0.01
    assert all(a.end <= b.start + 1e-6 for a, b in zip(w, w[1:]))


def test_align_by_silences_uses_longest_gaps():
    words = align_by_silences("Un deux. Trois quatre.", 4.0, [(0.5, 0.6), (1.8, 2.4), (3.0, 3.1)])
    assert words[1].end <= 1.81 and words[2].start >= 2.39


def test_map_to_script_keeps_script_spelling():
    heard = [Word(text="exode", start=0.0, end=0.4), Word(text="arrive", start=0.5, end=0.9)]
    out = map_to_script("Exode arrive bientôt !", heard)
    assert [w.text for w in out] == ["Exode", "arrive", "bientôt", "!"]
    assert out[0].start == 0.0 and out[1].start == 0.5 and out[2].start >= 0.9


def test_elevenlabs_alignment_to_words():
    chars = list("Salut toi")
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    w = words_from_alignment(chars, starts, ends)
    assert [x.text for x in w] == ["Salut", "toi"] and abs(w[1].start - 0.6) < 1e-9


def test_ass_helpers():
    assert ass_color("#7C5CFF") == "&H00FF5C7C"
    assert ass_time(62.346) == "0:01:02.35"
    words = [Word(text=t, start=i, end=i + 0.9) for i, t in enumerate("Les quêtes arrivent enfin, rejoins-nous".split())]
    chunks = chunk_words(words)
    assert [len(c) for c in chunks] == [3, 1, 1]


def test_build_ass_contains_scene_texts_and_captions():
    sb = Storyboard(headline="Devlog", scenes=[Scene(type="title", text="Titre {x}"), Scene(type="image", media="a.png")])
    tl = [TimedScene(sb.scenes[0], 0, 2), TimedScene(sb.scenes[1], 2, 5)]
    ass = build_ass(sb, tl, [Word(text="Bonjour", start=0.5, end=1.0)], 1080, 1920, "#7C5CFF", "#FFD166")
    assert "PlayResX: 1080" in ass and "Titre (x)" in ass
    assert ",Headline,," in ass and "Devlog" in ass
    assert ass.count(",Caption,,") == 1 and "Bonjour" in ass
