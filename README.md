# Gaasielektrijaamade planeeringute scraper

Tööriist, mis kogub **avalikest** planeeringu-, keskkonnamõju hindamise (KMH/EIA)
ja loamenetluse portaalidest infot **gaasiturbiinidel ja gaasimootoritel
põhinevate elektrijaamade** projekteerimise ja planeerimise kohta:

- **joonised** (asendiplaanid, situatsiooniskeemid, põhijoonised, DWG/DXF),
- **kirjeldused** (seletuskirjad, KMH aruanded, tehnilised kirjeldused),
- **ohutusdokumendid** (riskianalüüsid, Seveso, ohutusaruanded),
- **taristu** (võrguühendused, gaasitrassid, alajaamad),
- **load ja otsused** (keskkonnaload, kompleksload, KMH otsused).

Leitud dokumendid liigitatakse võimsusklassidesse **≤20 MW, ≤50 MW, ≤100 MW,
≤200 MW** (ja >200 MW), kui tekstist õnnestub MW-arv tuvastada.

Kaetud riigid: **Eesti, Läti, Leedu, Soome, Rootsi, Poola, Tšehhi**.

## Paigaldus

```bash
pip install -r requirements.txt
```

`pypdf` on valikuline – kui see on paigaldatud, loeb scraper MW-arvud ja
dokumenditüübid ka PDF-ide sisust, mitte ainult failinimedest ja lingitekstidest.

## Kasutamine

```bash
# Näita seadistatud allikaid
python -m gas_plant_scraper list-sources

# Kogu kõigist riikidest, kuni 100 dokumenti allika kohta
python -m gas_plant_scraper run

# Ainult Eesti ja Soome, kuni 50 dokumenti allika kohta
python -m gas_plant_scraper run --countries EE,FI --max-docs 50

# Ainult Tšehhi EIA register, ilma faile alla laadimata (ainult kataloog)
python -m gas_plant_scraper run --sources cz_eia --no-download

# Kokkuvõte ja eksport
python -m gas_plant_scraper report
python -m gas_plant_scraper export --format csv
```

Tulemused:

- `data/<RIIK>/<allikas>/…` – alla laetud dokumendifailid,
- `data/catalog.sqlite` – kataloog (URL, pealkiri, tüüp, MW-klass, allikas,
  kohalik failitee),
- `data/catalog.csv` ja `data/catalog.jsonl` – sama kataloog eksporditult.

## Kuidas see töötab

1. Iga allika (vt `config/sources.yaml`) seed-lehtedelt ja otsingu-URLidest
   alustatakse crawl'i. Otsingusõnad on igas kohalikus keeles
   (`gaasiturbiin`, `kaasuvoimalaitos`, `turbina gazowa`, `plynová elektrárna`
   jne – vt `gas_plant_scraper/keywords.py`).
2. Järgitakse ainult linke, mille tekst/URL viitab gaasijaamadele
   (`--min-relevance` reguleerib rangust), lubatud domeenide piires ja
   seatud sügavuseni.
3. Dokumendifailid (PDF, DWG, DXF, DOCX, ZIP …) laetakse alla, liigitatakse
   (joonis / kirjeldus / ohutus / taristu / luba) ja MW-arvud loetakse välja
   lingi kontekstist, lehe tekstist ning võimalusel PDF-i sisust.
4. Kõik kirjed lähevad SQLite-kataloogi; duplikaate ei lisata, seega
   korduskäivitus jätkab poolelijäänud kohast.

Scraper on viisakas: vaikimisi 2 s viivitus hosti kohta, arvestab
`robots.txt`-ga, piirab lehtede ja failide arvu allika kohta.

## Allikad riigiti

| Riik | Allikas | Mis sealt tuleb |
|------|---------|-----------------|
| EE | KOTKAS (kotkas.envir.ee) | KMH aruanded, keskkonnaload, ohutusdokumendid |
| EE | PLANK (planeeringud.ee) | detail- ja eriplaneeringute joonised, seletuskirjad |
| EE | Ametlikud Teadaanded | planeeringu- ja KMH-menetluste teated |
| LV | VPVB (vpvb.gov.lv) | IVN (KMH) projektid ja aruanded |
| LV | ĢeoLatvija/TAPIS | territoriaalplaneeringud |
| LT | AAA (aaa.lrv.lt) | PAV (KMH) teated ja aruanded |
| LT | TPDRIS | planeerimisdokumendid |
| FI | ymparisto.fi | YVA-projektid (arviointiselostus + joonised) |
| FI | AVI Lupa-Tietopalvelu (ylupa.avi.fi) | keskkonnalubade PDF-id |
| SE | Länsstyrelsen | miljöprövning'u info; dokumendid diariumi kaudu |
| PL | Baza OOŚ (baza.gdos.gov.pl) | KMH andmebaas |
| PL | Ekoportal | keskkonnainfo kaardid |
| CZ | CENIA EIA (portal.cenia.cz) | EIA projektid, dokumentace, situace-joonised |
| CZ | IPPC (ippc.mzp.cz) | kompleksload |

**Märkused:**

- Mitu portaali (PLANK, ĢeoLatvija, TPDRIS, ylupa.avi.fi) on
  JavaScripti-põhised SPA-rakendused – automaatne crawl leiab sealt vähem;
  parim tulemus tuleb, kui otsid portaalis käsitsi projekti üles ja lisad
  projekti/dokumendi URLi vastava allika `seeds`-nimekirja
  (`config/sources.yaml`) ning käivitad scraperi uuesti.
- Rootsis pole ühtset avalikku dokumendiportaali – load menetlevad
  miljöprövningsdelegationid ja mark- och miljödomstolid; dokumendid saab
  küsida asutuse diariumist (offentlighetsprincipen alusel, tavaliselt
  e-kirjaga, tasuta).
- Häid näidisprojekte (märksõnad, mida portaalidest otsida): Kiisa
  avariielektrijaam (EE, 250 MW gaasimootorid), Tallinna ja Tartu
  koostootmisjaamad, Kaunas/Vilnius kogeneracinė jėgainė (LT),
  Riia TEC (LV), soomes Wärtsilä gaasimootorjaamad, Poolas CCGT Dolna Odra
  ja Grudziądz, Tšehhis paroplynové zdroje.

## Seadistamine

- **Uue allika lisamine:** lisa kirje `config/sources.yaml` faili
  (seeds, lubatud domeenid, soovi korral otsingu-URL malliga `{query}`).
- **Otsingusõnade muutmine:** `gas_plant_scraper/keywords.py`
  (`SEARCH_TERMS` – otsing, `DOC_TYPE_TERMS` – liigitus).
- **Võimsusklassid:** `gas_plant_scraper/classify.py` (`MW_BUCKETS`).

## Testid

```bash
pip install pytest
python -m pytest tests/
```

Testid ei vaja võrku – crawl'i testitakse kohaliku fikstuurserveri vastu.

## Õiguslik märkus

Tööriist laeb ainult avalikult kättesaadavaid haldusdokumente (planeeringud,
KMH aruanded, load), arvestab robots.txt-ga ja hoiab madalat päringusagedust.
Alla laetud dokumentide edasisel kasutamisel järgi allika portaali
kasutustingimusi ja autoriõigusi – projekteerimisjoonised on tüüpiliselt
autoriõigusega kaitstud ka siis, kui need on menetluse käigus avalikustatud.
