# RUN_STATUS — reaalajas kraapimise tulemused (EE, CZ)

**Kuupäev:** 2026-09-07 (UTC)
**Haru:** `claude/gas-power-plant-scraper-58nmad`
**Käsk:** `python -m gas_plant_scraper -v run --countries EE,CZ --max-docs 20`
(+ sihitud kordusjooks CZ allikatele parandatud seemne-URL-idega, vt allpool)

## Kokkuvõte

Esimene täisjooks andis **0 dokumenti** — iga allikas ebaõnnestus eri põhjusel
(vt tabel). Diagnoosi järel tegin Tšehhi allikatele sihitud kordusjooksu
parandatud lähte-URL-idega, mis andis **18 dokumenti** (kõik alla laetud).
Eesti portaalidest ei õnnestunud sellest keskkonnast midagi kätte saada —
põhjused on keskkonna- ja portaalipoolsed, mitte skreeperi loogika vead.

## Aruande väljund (`python -m gas_plant_scraper report`)

```
Dokumente kokku: 18
Riigi järgi:  {'CZ': 18}
MW-klassi järgi: {'<=50 MW': 11, 'teadmata': 7}
Tüübi järgi:  {'unclassified': 9, 'description': 8, 'infrastructure': 1, 'permit': 1}
```

## Allikate kaupa

| Allikas | Lehti | Dokumente | Vigu | Tulemus |
|---|---|---|---|---|
| ee_kotkas | 0 | 0 | 8 | HTTP 403 kõigile päringutele — WAF/robotitõrje |
| ee_plank | 8 | 0 | 0 | Chromiumi render ebaõnnestus (keskkonna proksi), HTTP-varuvariant sai ainult tühja SPA-kesta |
| ee_ametlikud_teadaanded | 0 | 0 | 8 | robots.txt keelab `/avalik` — skreeper austab robots.txt-d |
| cz_eia (esimene jooks) | 1 | 0 | 0 | Seemneleht näitab vaid viimaste projektide loendit; otsing nõuab POST-i |
| cz_eia (kordusjooks) | 16 | **18** | 0 | Gaasiprojektide detailvaated leitud käsitsi POST-otsinguga, seemnetena ette antud |
| cz_ippc (esimene jooks) | 0 | 0 | 1 | Konfis olev route `/ippc/ippc.nsf/vydana-povoleni` annab 404 (portaal kolis) |
| cz_ippc (kordusjooks) | 1 | 0 | 0 | Uus route `/ippc/ippc.nsf/index.xsp` avaneb, aga XPages-rakendus vajab JS-i/postback-e — linke ei ole staatilises HTML-is |

## Miks Eesti portaalid tühjaks jäid (täpsem diagnoos)

- **KOTKAS (kotkas.envir.ee)** — tagastab 403 ka täielike brauseripäistega;
  tõrje käib IP/sõrmejälje (andmekeskuse liiklus), mitte User-Agenti järgi.
  Tavabrauserist töötab. Sellest keskkonnast kättesaamatu.
- **PLANK (planeeringud.ee)** — vajab Playwrighti renderdust, aga selle
  jooksukeskkonna väljuv proksi (TLS-i vahelthaare) katkestab peata Chromiumi
  TLS-kätluse (`ERR_CONNECTION_RESET` isegi example.com-ile). Osaline
  workaround (`--ssl-version-max=tls1.2`) avas example.com-i, kuid Eesti
  hostid jäid ikka kinni. HTTP-varuvariant toob ainult SPA tühja kesta,
  sest otsing elab URL-i fragmendis (`#/planning/search`), mida server ei näe.
- **Ametlikud Teadaanded** — robots.txt keelab `/avalik/otsing` teed;
  skreeper austab seda teadlikult. Vajaks kas robots-erandit (mitte soovitatav)
  või ametlikku API-t/RSS-i.

## Soovitused edasiseks

1. **cz_eia**: lisada `config/sources.yaml`-i POST-otsingu tugi või hoida
   seemnetena gaasiprojektide detail-URL-e (need on stabiilsed:
   `https://portal.cenia.cz/eiasea/detail/EIA_xxx?lang=cs`). Otsing vajab
   välju `typHledani=rychle&quickSearch=<sõna>` POST-ina samale vaatele.
2. **cz_ippc**: uuendada seed `https://ippc.mzp.cz/ippc/ippc.nsf/index.xsp`
   peale ja lisada renderdus (XPages vajab JS-i), või kasutada rakenduse
   sisemisi loendivaateid, kui need GET-iga avanevad.
3. **ee_kotkas / ee_plank**: jooksutada elukoha-/kontorivõrgust (mitte
   andmekeskusest) või kasutajapoolse brauseri kaudu; selles keskkonnas
   lisaks vaja proksi, mis ei lõhu Chromiumi TLS 1.3 kätlust.
4. **ee_ametlikud_teadaanded**: uurida ametlikku liidest (nt teadaannete
   RSS/otsepäringud), kuna robots.txt keelab otsingulehtede kraapimise.

## Failid

- `results/catalog.csv`, `results/catalog.jsonl` — 18 dokumendi kataloog
  (URL, projekt, tüübiklassifikatsioon, MW-hinnang, kohalik failitee).
- Allalaetud failid ise (PDF/DOC/ZIP, ~kokku 40+ MB) on `data/CZ/` kaustas,
  mis on gitignore'itud ega ole commit'is.
