# Nexi – OBA Conversational AI

Nexi is een AI-zoekassistent ontwikkeld voor de Openbare Bibliotheek Amsterdam (OBA).  
Het systeem helpt gebruikers om boeken, activiteiten en veelgestelde vragen te vinden via natuurlijke taal.  
De backend combineert de OpenAI Responses API met Typesense en de officiële OBA API’s, en is geschikt voor zowel tekst- als voicefrontends.

## ⚙️ Functionaliteiten
- **Conversaties**  
  Elk gesprek loopt via een `conversation_id` zodat context behouden blijft. Nexi onthoudt de laatste zoekresultaten en kan daarop verder redeneren.
- **Boeken zoeken**  
  Ondersteunt twee collecties:  
  - **Reguliere collectie** van de OBA  
  - **OBA Kraaiennest collectie**  
  Er kan gezocht worden op titel, auteur of contextuele vragen via Typesense embeddings, met filters op taal en leeftijdscategorie.
- **Vergelijkbare boeken**  
  Vind suggesties op basis van genre, thema of schrijfstijl, exclusief de originele titel/auteur.
- **FAQ**  
  Antwoorden uit de OBA FAQ-database (o.a. over lidmaatschap, tarieven, locaties).
- **Agenda**  
  Vragen naar activiteiten worden vertaald naar OBA-agenda filters (locatie, leeftijd, type activiteit, periode).
- **Proxy-routes**  
  Detailpagina’s voor boeken en agenda-items via de officiële OBA API’s.

## 🛠️ Architectuur
De applicatie is opgebouwd uit losse services:

- **`app.py`** – Flask server met routes voor conversaties, filters, en proxies.  
- **`conversations_client.py`** – Stuurt gesprekken aan met de OpenAI Responses API en verwerkt toolcalls.  
- **`conversations_config.py`** – Bevat systeem-instructies, modelkeuze en fallback-boodschappen.  
- **`oba_config.py`** – Centrale configuratie: Typesense collections, filters en tool-schemas.  
- **`oba_tools.py`** – Implementaties van toolfuncties voor boeken, agenda, vergelijkingen en FAQ.  
- **`oba_helpers.py`** – Hulpfuncties voor Typesense en OBA API’s + uniform envelop-formaat voor frontend.  

De backend is zo opgezet dat zowel een **tekst-frontend** als de **Nexi Voice frontend** gebruik kan maken van dezelfde routes en logica.

## 🚀 Installatie
1. Clone dit project.  
2. Zorg voor Python 3.12+.  
3. Installeer afhankelijkheden:  
   ```bash
   pip install -r requirements.txt
   ```
   4. Maak een `.env` bestand met o.a.:  
      ```
        OPENAI_API_KEY
       TYPESENSE_API_KEY
       TYPESENSE_API_URL
       COLLECTION_BOOKS_KN
       COLLECTION_BOOKS
       COLLECTION_FAQ
       COLLECTION_EVENTS
      ```
5. Start de server:  
   ```bash
   flask run
   ```

## 🔌 API-routes
- `POST /start_thread` → Start een nieuw gesprek, retourneert `thread_id`.  
- `POST /send_message` → Stuur gebruikersinput + `thread_id`, Nexi antwoordt met resultaten.  
- `POST /apply_filters` → Pas filters toe op bestaande resultaten.  
- `GET /proxy/resolver` → Haal detailinformatie op voor een boek.  
- `GET /proxy/details` → Haal uitgebreide metadata op voor een item.  

## 📋 Taken & ontwikkeling
Tijdens de ontwikkeling zijn de volgende onderdelen gerealiseerd:
- Ontwerp van **systeem-instructies** voor Nexi’s taalstijl (kort, helder, B1-niveau).  
- Implementatie van een **toolcalling-framework** bovenop de OpenAI Responses API.  
- Integratie met bestaande **Typesense** voor boeken- en FAQ-zoekopdrachten, inclusief aparte collectie voor **OBA Kraaiennest**.  
- XML-parsing en filters voor **OBA Agenda API**.  
- Logging, foutafhandeling en proxy-routes in Flask.
- Configuratiebestand met **agenda-filters, leeftijdscategorieën en locaties**.
- Backend zo opgezet dat zowel **Nexi Text** als **Nexi Voice** frontends erop aangesloten kunnen worden.

Copyright (c) 2025 / OBA . Licensed under the MIT License / CC BY 4.0
