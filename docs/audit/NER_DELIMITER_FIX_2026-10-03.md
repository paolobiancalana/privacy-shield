# Correzione delimitatori NER — 3 ottobre 2026

## Modifica
Nel decoder condiviso, i token composti da una virgoletta delimitatrice terminano
lo span e azzerano il word_id precedente. Il primo subword del nome successivo
viene così valutato anche se il tokenizer lo raggruppa con la virgoletta.
Gli apostrofi interni tra caratteri alfanumerici mantengono il comportamento
precedente. Non cambiano pesi, tokenizer, inferenza, API o architettura.

File runtime: `app/infrastructure/adapters/ner_detection.py` (14 righe aggiunte).
Il comportamento non estende automaticamente il supporto a ogni delimitatore o
costrutto di tutti i linguaggi.

## TDD alle interfacce concordate
- Primo rosso: `detect('fullName = "Mario Rossi"')` restituiva Rossi [18,23)
  anziché Mario Rossi [12,23). Dopo la correzione passa.
- Secondo rosso: il nome tra apici singoli restituiva Rossi' [14,20) anziché
  Mario Rossi [8,19). Dopo la gestione degli apici passa.
- Regressioni: stringa Java, cityField nei due linguaggi che fallivano con
  decoder indiscriminato, PersonService, prosa, D'Angelo e Jean-Pierre Dupont.
- API: caso aggiunto al test esistente di 10.000 caratteri; né Mario né Rossi
  rimangono nel testo, virgolette e punto e virgola restano integri, reidratazione
  identica all'input. FastAPI reale locale, ONNX reale, Redis simulato con fakeredis.
- Suite mirata: 29 passati. Nessuna inferenza esterna o dati personali reali.

## Benchmark diagnostico invariato

| Composito regex + NER | Prima | Dopo |
|---|---:|---:|
| Entità interamente coperte | 18/51 (35,29%) | 42/51 (82,35%) |
| Input positivi con PII residue | 33/42 | 9/42 |
| Negativi con falsi rilevamenti | 0/12 | 0/12 |

Nessuna regressione di copertura completa per caso su questo corpus. Restano
errori su località nei commenti, alcuni indirizzi, escape e email concatenate.
Percentuali relative ai soli 54 casi sintetici correlati; non sono stime di
sicurezza generale. I casi hanno contribuito alla scelta della correzione:
serve un holdout indipendente per qualificare il prodotto.

Evidenze: `NER_DELIMITER_FIX_2026-10-03.json`, con hash modello/corpus/sorgenti e
risultati per caso. Il commit nel JSON è la base Git; la modifica è nel working tree.

## Riproduzione

```bash
HF_HUB_OFFLINE=1 python3 -m pytest tests_app/security/test_ner_delimiters.py tests_app/security/test_ner_windows.py -q
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false python3 -m eval.code_pii_benchmark --output /tmp/ps-delimiter-benchmark.json
```

I test col modello vengono saltati dove i pesi non sono presenti: un CI senza
modello non sostituisce questa verifica locale. Il vecchio probe
`eval.diagnose_name_boundary` contiene intenzionalmente un'asserzione sul difetto
precedente e non è un test di accettazione della correzione; le tracce storiche
restano nei report della diagnosi.

Nessun push o deploy effettuato per questa correzione.

Verifica finale: **813 test passati**, 26 warning di deprecazione; **57 test dedicati** crittografia/span fusion/regex passati. Suite completa eseguita con modello locale, credenziali Supabase disabilitate e controlli host di sicurezza verso privacyshield. Nessuna modifica remota.
