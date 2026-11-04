from newsautopublisher.publishers.x_intent import build_intent_url
from newsautopublisher.validate import scan_leaks, x_weighted_length


def test_x_length_plain_and_urls():
    assert x_weighted_length("Bonjour") == 7
    assert x_weighted_length("Voir https://example.com/un/tres/long/chemin/qui/depasse") == 5 + 23
    assert x_weighted_length("fab.com/listings/42") == 23
    assert x_weighted_length("abc", extra_url="https://x.com") == 3 + 1 + 23


def test_x_length_emoji_counts_double():
    assert x_weighted_length("🚀") == 2
    assert x_weighted_length("❤️") == 2  # le sélecteur de variante ne compte pas
    assert x_weighted_length("é") == 1


def test_leaks_detect_secrets_without_copying_them():
    found = scan_leaks("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 et https://discord.com/api/webhooks/1/x")
    labels = {f[1] for f in found}
    assert "jeton GitHub" in labels and "webhook Discord" in labels
    assert all(f[0] == "error" for f in found)
    assert not any("ABCDEFGHIJ" in f[2] for f in found)


def test_leaks_warn_on_local_paths_and_emails():
    found = scan_leaks(r"Fichier D:\Dev\Exode\secret.txt, contact moi@exemple.fr, serveur 192.168.1.20")
    labels = {f[1] for f in found}
    assert {"chemin local Windows", "adresse e-mail", "adresse IP privée"} <= labels
    assert all(f[0] == "warning" for f in found)


def test_no_leak_in_normal_text():
    assert scan_leaks("Nouveau devlog d'Exode ! Les quêtes arrivent. https://discord.gg/exode #gamedev") == []


def test_intent_url_encoding():
    url = build_intent_url("Les quêtes arrivent ! #Exode", "https://discord.gg/exode")
    assert url.startswith("https://x.com/intent/post?text=")
    assert "%23Exode" in url and "qu%C3%AAtes" in url and "url=https%3A%2F%2Fdiscord.gg%2Fexode" in url
    assert "+" not in url
