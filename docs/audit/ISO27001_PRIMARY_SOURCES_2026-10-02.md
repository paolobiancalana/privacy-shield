# Privacy Shield — fonti normative e criteri per la gap analysis

Data di consultazione: **2 ottobre 2026**. Ricerca di supporto; questo file non attesta certificazione, conformità legale o stato effettivo dei controlli del progetto. Le conclusioni tecniche e organizzative richiedono evidenze del perimetro auditato. Sono riportate sintesi e riferimenti, non il testo integrale delle norme.

## 1. Edizione applicabile, perimetro e controlli

Il catalogo ISO identifica **ISO/IEC 27001:2022, terza edizione**, come norma pubblicata e le associa **Amendment 1:2024**. La certificazione riguarda l'ISMS dell'organizzazione entro un perimetro dichiarato; un prodotto tecnicamente protetto o il certificato del suo hosting non costituiscono, da soli, certificazione dell'ISMS del cliente. [ISO — scheda della norma](https://www.iso.org/standard/27001), [ISO — Amendment 1:2024](https://www.iso.org/standard/88435.html).

L'amendamento richiede di considerare la rilevanza del cambiamento climatico nel contesto e i possibili requisiti pertinenti delle parti interessate. Nel caso SaaS l'analisi può riguardare disponibilità elettrica, eventi ambientali e dipendenze dai datacenter. Non implica automaticamente una policy ambientale separata: occorre una determinazione motivata e, se pertinente, trattamento nei rischi ISMS. [Comunicato congiunto ISO/IAF del febbraio 2024](https://iaf.nu/en/news/iaf-and-iso-publish-joint-communique/). La pagina IAF è oggi archivio storico, come dichiara il sito.

I requisiti delle **clausole 4–10 non sono escludibili** quando si dichiara conformità. Il testo pubblico dell'introduzione e della clausola 1 è verificabile nell'[anteprima ISO/IEC 27001:2022 distribuita da GSO](https://gso-sims-preview-doc-aws.s3-eu-west-1.amazonaws.com/iso-iec-27001-2022-en.html).

Annex A contiene **93 controlli**: 37 organizzativi, 8 persone, 14 fisici e 34 tecnologici. La selezione deriva da rischi e requisiti: occorre confrontarla con l'intero catalogo, giustificare le esclusioni, documentare i controlli necessari e lo stato di implementazione nella **Statement of Applicability (SoA)**. Possono servire controlli ulteriori. Non è un obbligo indiscriminato di implementare tutti i 93. [NQA — guida all'implementazione, pp. 19–21](https://www.nqa.com/medialibraries/NQA/NQA-Media-Library/PDFs/NQA-ISO-27001-Implementation-Guide.pdf).

**Fonte per verificare tutti gli identificativi:** l'[anteprima pubblica GSO di ISO/IEC 27002:2022](https://gso-sims-preview-doc-aws.s3-eu-west-1.amazonaws.com/iso-iec-27002-2022-en.html) contiene l'indice completo: 5.1–5.37, 6.1–6.8, 7.1–7.14, 8.1–8.34. In una matrice Annex A 27001 i riferimenti corrispondenti sono A.5.1–A.8.34. La [scheda ISO di 27002:2022](https://www.iso.org/standard/75652.html) distingue la guida ai controlli dai requisiti certificabili di 27001. Non copiare l'intera norma: procurare una copia autorizzata e controllata per il programma di certificazione.

## 2. Documentazione ed evidenze da verificare

Il minimo documentale da verificare nelle clausole 4–10 comprende:

| Riferimento | Informazione/evidenza da mantenere o conservare |
|---|---|
| 4.3 | Perimetro ISMS |
| 5.2 | Politica di sicurezza |
| 6.1.2 | Processo di valutazione del rischio |
| 6.1.3 | Processo di trattamento, SoA, piano di trattamento e accettazione dei rischi residui |
| 6.2 | Obiettivi di sicurezza |
| 7.2 | Evidenze delle competenze |
| 7.5 | Informazioni richieste e quelle necessarie all'efficacia ISMS, sottoposte a controllo |
| 8.1 | Evidenze sufficienti che i processi operativi sono eseguiti come pianificato |
| 8.2–8.3 | Risultati delle valutazioni e dei trattamenti del rischio |
| 9.1 | Risultati di monitoraggio e misurazione |
| 9.2.2 | Programma audit e risultati |
| 9.3.3 | Risultati del riesame direzionale |
| 10.2 | Non-conformità, azioni intraprese e risultati delle azioni correttive |

Riferimenti di riscontro: [BSI — materiale ISO 27001:2022, sezione “Minimum Document Requirement”, slide 28–31](https://www.bsigroup.com/globalassets/localfiles/en-th/webinars/webinar-iso27001-2022-transition-november-2022-r4.pdf); [NQA — guida, pp. 14–28](https://www.nqa.com/medialibraries/NQA/NQA-Media-Library/PDFs/NQA-ISO-27001-Implementation-Guide.pdf). Il vecchio URL BSI è reperibile nell'indice di ricerca ma al download reindirizza alla homepage: non è stato recuperato integralmente durante questa verifica; la lista va convalidata sulla copia controllata della norma prima dell'audit formale.

Un registro o documento può soddisfare più requisiti. Manuale ISMS, procedura incidenti, DR plan, inventario asset, registro fornitori, policy HR e crittografica sono mezzi pratici di attuazione: **non dichiararli tutti documenti autonomi universalmente obbligatori**. La loro necessità e profondità dipendono dai controlli applicabili, dai rischi, dagli obblighi esterni e dal funzionamento reale. La guida NQA ammette SoA tabellare e verbali sintetici; versione, approvazione, accesso e conservazione contano più del numero di file. [NQA — guida, pp. 19, 23 e 27](https://www.nqa.com/medialibraries/NQA/NQA-Media-Library/PDFs/NQA-ISO-27001-Implementation-Guide.pdf).

## 3. Fase 1, Fase 2 e classificazione dei rilievi

Nel processo pubblicato da NQA, **Fase 1** valuta prontezza, documentazione, scope, implementazione e considerazione degli obblighi legali; produce anche aree di attenzione per Fase 2. **Fase 2** campiona processi ed evidenze per valutare conformità ed efficacia nella pratica. Le NC maggiori devono essere corrette e verificate prima della certificazione; per ISMS sono essenziali audit interni e riesame direzionale effettivamente attuati. [NQA — processo di certificazione](https://www.nqa.com/en-us/certification/systems/our-process).

NQA indica nel proprio processo almeno tre mesi di operatività: è una condizione pubblicata dall'ente, **non una durata minima universale da attribuire a ISO 27001**. Una roadmap tecnica di sei settimane non prova automaticamente maturità sufficiente alla Fase 2. La durata di raccolta evidenze va concordata con l'ente e commisurata ai processi. [NQA — stesso processo](https://www.nqa.com/en-us/certification/systems/our-process).

Secondo ISO/IEC 17021-1, §§3.11–3.13, una NC è il mancato soddisfacimento di un requisito. È **maggiore** se compromette la capacità del sistema di conseguire i risultati previsti; può emergere da una carenza sistemica o da più NC minori correlate. È **minore** se non compromette tale capacità. [Anteprima ufficiale GSO della norma, definizioni 3.11–3.13](https://gso-sims-preview-doc-aws.s3-eu-west-1.amazonaws.com/gso-iso-iec-17021-1-2021-en.html).

**Regola applicativa per questo lavoro:** chiamare i rilievi “potenziali NC” nella gap analysis; la classificazione finale compete all'audit formale. “Non rinvenuto nel repository” significa assenza di evidenza nel campione, non prova che una procedura o un contratto non esistano altrove. Le osservazioni segnalano miglioramenti quando il requisito non risulta violato. Un Readiness Score è una stima con pesi e denominatore espliciti, non una percentuale ufficiale ISO né una probabilità di certificazione.

## 4. GDPR, pseudonimizzazione e sovranità

Il GDPR definisce la pseudonimizzazione attraverso l'uso di informazioni aggiuntive conservate separatamente e protette. L'anonimato richiede invece che l'interessato non sia identificabile mediante mezzi ragionevolmente utilizzabili. Ne segue che **una tokenizzazione reversibile con vault non dimostra anonimizzazione**; per il soggetto che possiede mappa e mezzi di riconduzione restano dati personali. [GDPR, art. 4(5) e considerando 26–29](https://eur-lex.europa.eu/legal-content/EN-FR/TXT/?uri=CELEX%3A32016R0679).

Non va però affermato che qualsiasi dato pseudonimizzato sia necessariamente personale per qualsiasi destinatario. La CGUE, nel caso **C-413/23 P del 4 settembre 2025**, distingue la ragionevole identificabilità nella posizione del destinatario e conferma, nel caso esaminato, la valutazione dal punto di vista del titolare ai fini dell'obbligo di informazione. [CGUE — sentenza su EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex%3A62023CJ0413). Applicazione al progetto: eventuali claim “anonimo al modello AI” necessitano una valutazione concreta del contenuto residuo, dei metadati, dei mezzi del destinatario e dei possibili collegamenti; TTL e sostituzione dei nomi non bastano a provarli.

Aggiornamento 2026: l'EDPB ha pubblicato nuove linee sull'anonimizzazione che considerano tale sentenza, **ancora in consultazione fino al 30 ottobre 2026**. Non trattarle come versione finale al 2 ottobre. Anche le linee 01/2025 reperite sulla pseudonimizzazione sono marcate versione per consultazione. [EDPB — comunicato 8 luglio 2026](https://www.edpb.europa.eu/news/edpb-sheds-light-on-anonymisation-and-web-scraping-for-generative-ai-and-adopts-final-version_en), [EDPB — 01/2025](https://www.edpb.europa.eu/system/files/2025-01/edpb_guidelines_202501_pseudonymisation_en.pdf).

La **residenza UE non dimostra da sola assenza di trasferimenti o esposizione a richieste estere**. L'EDPB include l'accesso remoto di entità extra-SEE tra i trasferimenti; richiede mappare sub-responsabili, destinazioni, strumenti e condizioni concrete. La pseudonimizzazione può fungere da misura supplementare se informazioni aggiuntive e mezzi di reidentificazione sono protetti e l'analisi esclude ragionevoli attribuzioni usando dati esterni. [EDPB — Raccomandazioni 01/2020, versione finale, §§9–13, 85–89](https://www.edpb.europa.eu/system/files/documents/2021-06/edpb_recommendations_202001vo.2.0_supplementarymeasurestransferstools_en.pdf).

Le richieste dirette di autorità estere non diventano automaticamente eseguibili nell'UE. Una risposta che trasferisca dati deve rispettare base giuridica e Capo V GDPR; vanno inoltre valutati i flussi tra eventuale controllante extra-UE e controllata UE. Questo giustifica una verifica di entità contrattuale, accessi, catena societaria e subfornitori; non prova di per sé né una violazione né un'immunità dal CLOUD Act. [EDPB — linee 02/2024, definitive v2.1 del giugno 2025, sintesi e §8](https://www.edpb.europa.eu/system/files/2025-06/edpb_guidelines_202402_article48_v2_en.pdf).

## 5. OVH e controlli ereditati dal fornitore

OVH pubblica una lista di prodotti coperti da ISO27k, aggiornata al **2 giugno 2026**, con certificati riferiti fra l'altro a ISO/IEC 27001:2022. Il catalogo distingue prodotti certificati e non certificati. Non vi compare una voce esplicita “VPS”: ciò **non consente di concludere né inclusione né esclusione** del servizio effettivamente acquistato. Richiedere certificato corrente, allegato di scope, datacenter e categoria del servizio, entità contrattuale, responsabilità condivise ed evidenze di riesame del fornitore. [OVH — prodotti coperti dalle certificazioni ISO27k](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/security-certifications).

Per i controlli fisici, la proposta operativa è separare evidenze del datacenter da quelle di sedi, postazioni, lavoro remoto e smaltimento dispositivi dell'organizzazione. L'outsourcing non autorizza a marcare automaticamente tutto A.7 come “non applicabile”. Questo è un criterio di audit basato su perimetro e responsabilità, da confermare nella SoA.

## 6. Indice operativo dei 93 controlli

Etichette italiane abbreviate di lavoro, non traduzione ufficiale né riproduzione dei requisiti. Numerazione verificata nell'[indice dell'anteprima GSO di ISO/IEC 27002:2022](https://gso-sims-preview-doc-aws.s3-eu-west-1.amazonaws.com/iso-iec-27002-2022-en.html). Norma e testo originale: © ISO/IEC 2022, diritti riservati. La matrice di audit deve aggiungere applicabilità, evidenza, responsabile e rilievo.

| Controllo | Etichetta |
|---|---|
| A.5.1 | Indirizzo |
| A.5.2 | Ruoli |
| A.5.3 | Separazione compiti |
| A.5.4 | Direzione |
| A.5.5 | Autorità |
| A.5.6 | Comunità |
| A.5.7 | Minacce |
| A.5.8 | Progetti |
| A.5.9 | Inventario |
| A.5.10 | Uso consentito |
| A.5.11 | Restituzione |
| A.5.12 | Classificazione |
| A.5.13 | Etichette |
| A.5.14 | Trasferimenti |
| A.5.15 | Accessi |
| A.5.16 | Identità |
| A.5.17 | Credenziali |
| A.5.18 | Autorizzazioni |
| A.5.19 | Fornitori |
| A.5.20 | Accordi |
| A.5.21 | Filiera |
| A.5.22 | Riesame fornitori |
| A.5.23 | Cloud |
| A.5.24 | Preparazione incidenti |
| A.5.25 | Triage |
| A.5.26 | Risposta |
| A.5.27 | Lezioni |
| A.5.28 | Evidenze |
| A.5.29 | Interruzioni |
| A.5.30 | Continuità ICT |
| A.5.31 | Obblighi |
| A.5.32 | Proprietà intellettuale |
| A.5.33 | Registrazioni |
| A.5.34 | Privacy |
| A.5.35 | Indipendenza |
| A.5.36 | Conformità |
| A.5.37 | Procedure |
| A.6.1 | Screening |
| A.6.2 | Assunzione |
| A.6.3 | Formazione |
| A.6.4 | Disciplina |
| A.6.5 | Cessazione |
| A.6.6 | Riservatezza |
| A.6.7 | Lavoro remoto |
| A.6.8 | Segnalazioni |
| A.7.1 | Perimetri |
| A.7.2 | Ingressi |
| A.7.3 | Locali |
| A.7.4 | Sorveglianza |
| A.7.5 | Minacce ambientali |
| A.7.6 | Aree protette |
| A.7.7 | Scrivania/schermo |
| A.7.8 | Collocazione |
| A.7.9 | Asset esterni |
| A.7.10 | Supporti |
| A.7.11 | Utenze |
| A.7.12 | Cablaggio |
| A.7.13 | Manutenzione |
| A.7.14 | Dismissione |
| A.8.1 | Endpoint |
| A.8.2 | Privilegi |
| A.8.3 | Restrizioni |
| A.8.4 | Sorgenti |
| A.8.5 | Autenticazione |
| A.8.6 | Capacità |
| A.8.7 | Malware |
| A.8.8 | Vulnerabilità |
| A.8.9 | Configurazioni |
| A.8.10 | Cancellazione |
| A.8.11 | Mascheramento |
| A.8.12 | Fughe |
| A.8.13 | Backup |
| A.8.14 | Ridondanza |
| A.8.15 | Log |
| A.8.16 | Monitoraggio |
| A.8.17 | Orologi |
| A.8.18 | Utility privilegiate |
| A.8.19 | Installazioni |
| A.8.20 | Reti |
| A.8.21 | Servizi rete |
| A.8.22 | Segmentazione |
| A.8.23 | Filtraggio web |
| A.8.24 | Crittografia |
| A.8.25 | SSDLC |
| A.8.26 | Requisiti applicativi |
| A.8.27 | Architettura |
| A.8.28 | Programmazione |
| A.8.29 | Collaudo sicurezza |
| A.8.30 | Sviluppo esterno |
| A.8.31 | Ambienti separati |
| A.8.32 | Modifiche |
| A.8.33 | Dati test |
| A.8.34 | Protezione durante audit |

## Limiti della ricerca

- Nessuna verifica tecnica applicativa o remota e nessuna modifica di configurazione eseguita nell'ambito di questa ricerca.
- Le anteprime ISO/GSO consentono riscontri su edizione, struttura, identificativi e alcune definizioni, non una revisione integrale di ogni requisito. NQA è fonte primaria sul proprio processo; la sua guida resta materiale interpretativo, non sostituisce la norma.
- Non verificati contratti, certificati individuali e scope del tenant/servizio OVH del progetto. Nessuna certificazione del fornitore è attribuita automaticamente a Privacy Shield.
- Nessuna attestazione personale di qualifica Lead Auditor e nessuna decisione di certificazione sono emesse da questo documento.
