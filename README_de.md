# HA Solcast PV Solar Forecast Integration

<!--[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)-->

[](https://github.com/custom-components/hacs)![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)![GitHub-Veröffentlichung](https://img.shields.io/github/v/release/BJReplay/ha-solcast-solar?style=for-the-badge)[](https://github.com/BJReplay/ha-solcast-solar/releases/latest)![hacs_downloads](https://img.shields.io/github/downloads/BJReplay/ha-solcast-solar/latest/total?style=for-the-badge)![GitHub-Lizenz](https://img.shields.io/github/license/BJReplay/ha-solcast-solar?style=for-the-badge)![GitHub-Commit-Aktivität](https://img.shields.io/github/commit-activity/y/BJReplay/ha-solcast-solar?style=for-the-badge)![Wartung](https://img.shields.io/maintenance/yes/2026?style=for-the-badge)

**Languages:** [🇦🇺 English](./README.md) | [🇫🇷 Français](./README-fr.md) | [🇩🇪 Deutsch](./README-de.md)

## Präambel

Diese kundenspezifische Komponente integriert die Solcast PV-Vorhersage für Hobbyisten in Home Assistant (https://www.home-assistant.io).

Es ermöglicht die Visualisierung der Solarprognose im Energie-Dashboard und unterstützt eine flexible Prognosedämpfung, die Anwendung einer harten Grenze für überdimensionierte PV-Systeme, einen umfassenden Satz von Sensor- und Konfigurationselementen sowie Sensorattribute mit vollständigen Prognosedetails zur Unterstützung von Automatisierung und Visualisierung.

Es handelt sich um eine ausgereifte Integration mit einer aktiven Community und reaktionsschnellen Entwicklern.

Diese Integration wurde nicht von Solcast erstellt, gewartet, unterstützt oder genehmigt.

> [!TIP]
>
> #### Supportanweisungen
>
> Bitte lesen Sie die [FAQ](https://github.com/BJReplay/ha-solcast-solar/blob/main/FAQ.md) , um häufige Probleme und Lösungen zu finden, sehen Sie sich alle angepinnten und aktiven [Diskussionen](https://github.com/BJReplay/ha-solcast-solar/discussions) an und prüfen Sie alle offenen [Issues,](https://github.com/BJReplay/ha-solcast-solar/issues) bevor Sie ein neues Issue erstellen oder eine neue Diskussion eröffnen.
>
> Bitte posten Sie keine „Ich auch“-Kommentare zu bereits bestehenden Problemen (Sie können aber gerne Probleme mit demselben Problem mit einem Daumen hoch bewerten oder Benachrichtigungen abonnieren) und gehen Sie nicht davon aus, dass ein ähnlicher Fehler derselbe ist. Sofern der Fehler nicht identisch ist, handelt es sich wahrscheinlich nicht um denselben Fehler.
>
> Überlegen Sie immer, ob Sie ein Problem aufgrund eines Integrationsfehlers melden sollten oder ob Sie Hilfe bei der Einrichtung oder Konfiguration Ihrer Integration benötigen. Falls Sie Unterstützung benötigen, prüfen Sie bitte, ob es bereits eine Diskussion gibt, die Ihre Frage beantwortet, oder stellen Sie Ihre Frage im Diskussionsbereich.
>
> Wenn Sie glauben, einen Fehler gefunden zu haben, befolgen Sie bitte die Anweisungen in der Problemvorlage, wenn Sie Ihr Problem melden.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

> [!NOTE]
>
> Diese Integration kann als Ersatz für die veraltete Oziee/HA-Solcast-Solar-Integration verwendet werden, deren Entwicklung eingestellt wurde und die daher entfernt wurde. Wenn Sie die Oziee-Version deinstallieren und anschließend diese Version installieren oder diese einfach über die alte herunterladen, bleiben alle bisherigen Einstellungen und der Verlauf erhalten. Falls Sie die Oziee-Integration **deinstalliert** und diese hier installiert haben, müssen Sie Solcast Solar erneut als Quelle für die Produktionsprognose in Ihrem Energie-Dashboard auswählen.

# Inhaltsverzeichnis

1. [Wichtige Solcast-Integrationskonzepte](#key-solcast-integration-concepts)
2. [Solcast-Anforderungen](#solcast-requirements)
3. [Installation](#installation)
    1. [HACS empfahl](#hacs-recommended)
    2. [Manuelle Installation in HACS](#installing-manually-in-hacs)
    3. [Manuelle Installation (ohne HACS)](#installing-manually-(not-using-hacs))
    4. [Beta-Versionen](#beta-versions)
4. [Konfiguration](#configuration)
    1. [Aktualisierung der Prognosen](#updating-forecasts)
        1. [Automatische Aktualisierung der Prognosen](#auto-update-of-forecasts)
        2. [Verwendung einer HA-Automatisierung zur Aktualisierung von Prognosen](#using-an-ha-automation-to-update-forecasts)
    2. [HA-Energie-Dashboard-Einstellungen einrichten](#set-up-ha-energy-dashboard-settings)
5. [Interaktion](#interacting)
    1. [Sensoren](#sensors)
    2. [Attribute](#attributes)
    3. [Aktionen](#actions)
    4. [Konfiguration](#configuration)
    5. [Diagnostik](#diagnostic)
6. [Erweiterte Konfiguration](#advanced-configuration)
    1. [Dämpfungskonfiguration](#dampening-configuration)
        1. [Automatische Dämpfung](#automated-dampening)
        2. [Einfache stündliche Dämpfung](#simple-hourly-dampening)
        3. [Granulare Dämpfung](#granular-dampening)
        4. [Lesen von Prognosewerten in einer Automatisierung](#reading-forecast-values-in-an-automation)
        5. [Ablesen der Dämpfungswerte](#reading-dampening-values)
    2. [Konfiguration der Sensorattribute](#sensor-attributes-configuration)
    3. [Konfiguration der harten Grenze](#hard-limit-configuration)
    4. [Konfiguration ausgeschlossener Websites](#excluded-sites-configuration)
    5. [Erweiterte Konfigurationsoptionen](#advanced-configuration-options)
7. [Beispielvorlagensensoren](#sample-template-sensors)
8. [Beispiel eines Apex-Diagramms für ein Dashboard](#sample-apex-chart-for-dashboard)
9. [Bekannte Probleme](#known-issues)
10. [Fehlerbehebung](#troubleshooting)
11. [Vollständige Integrationsentfernung](#complete-integration-removal)
12. [Änderungen](#Changes)

## Wichtige Solcast-Integrationskonzepte

Der Solcast-Dienst erstellt eine Prognose der Solarstromerzeugung für den Zeitraum von heute bis zu dreizehn Tagen im Voraus. Dies entspricht einem Gesamtzeitraum von bis zu vierzehn Tagen. Die Prognosen für die ersten sieben Tage werden durch die Integration als separater Sensor dargestellt und geben die prognostizierte Gesamtstromerzeugung für jeden Tag an. Weitere Prognosetage werden nicht über Sensoren angezeigt, können aber im Energie-Dashboard visualisiert werden.

Es sind auch separate Sensoren erhältlich, die die erwartete Spitzenleistung, den Zeitpunkt der Spitzenerzeugung und verschiedene Prognosen für die nächste Stunde, die nächsten 30 Minuten und mehr enthalten.

Sind mehrere Solaranlagen auf unterschiedlichen Dachausrichtungen vorhanden, können diese in Ihrem Solcast-Konto als separate „Dachstandorte“ mit unterschiedlichem Azimut, Neigungswinkel und Spitzenleistung konfiguriert werden. Für ein kostenloses Hobbykonto sind maximal zwei Standorte möglich. Die Prognosen dieser separaten Standorte werden zusammengeführt und bilden die Grundlage für die Daten des Integrationssensors und des Energie-Dashboards.

Solcast erstellt drei Schätzungen der Solarstromerzeugung für jeden halbstündigen Zeitraum aller prognostizierten Tage.

- Die Prognose, die als „zentral“ oder 50% oder am wahrscheinlichsten eintritt, wird durch die Integration als `estimate` dargestellt.
- '10%' oder 1 zu 10 'Worst-Case'-Prognose unter der Annahme einer höheren Wolkenbedeckung als erwartet, dargestellt als `estimate10` .
- '90%' oder 1 zu 10 'Best-Case'-Prognose unter der Annahme einer geringeren Wolkenbedeckung als erwartet, dargestellt als `estimate90` .

Die Details dieser verschiedenen Prognoseschätzungen finden sich in den Sensorattributen, die sowohl 30-Minuten-Intervalle pro Tag als auch berechnete Stundenintervalle über den Tag hinweg enthalten. Separate Attribute summieren die verfügbaren Schätzungen oder schlüsseln sie nach Solcast-Standort auf. (Diese Integration referenziert einen Solcast-Standort üblicherweise anhand seiner „Standortressourcen-ID“, die auf der Solcast-Website unter https://toolkit.solcast.com.au/ zu finden ist.)

Das Energie-Dashboard in Home Assistant wird mit historischen Daten gefüllt, die von der Integration bereitgestellt werden und bis zu zwei Jahre lang gespeichert werden. (Prognosedaten werden nicht als Home-Assistant-Statistiken gespeichert, sondern in einer von der Integration verwalteten `json` -Cache-Datei.) Angezeigt werden können entweder vergangene Prognosen oder geschätzte Ist-Werte, die in den Einstellungen ausgewählt werden können.

Die Anpassung der Prognosewerte an vorhersehbare Verschattungen zu bestimmten Tageszeiten ist automatisch oder durch die Festlegung von Dämpfungsfaktoren für stündliche oder halbstündliche Zeiträume möglich. Für überdimensionierte Solaranlagen kann zudem eine Obergrenze festgelegt werden, sodass die erwartete Stromerzeugung die maximale Nennleistung des Wechselrichters nicht überschreiten darf. Diese beiden Mechanismen sind die einzigen Möglichkeiten, die Solcast-Prognosedaten zu beeinflussen.

Solcast erstellt auch historische Schätzwerte für Ist-Werte. Diese sind in der Regel genauer als Prognosen, da hochauflösende Satellitenbilder sowie Wetter- und andere Klimadaten (z. B. zu Wasserdampf und Smog) zur Berechnung herangezogen werden. Die integrierte automatische Dämpfungsfunktion kann die geschätzten Ist-Werte nutzen und mit der Erzeugungshistorie vergleichen, um ein Modell der reduzierten prognostizierten Erzeugung unter Berücksichtigung lokaler Verschattung zu erstellen. Die geschätzten Ist-Werte können unabhängig davon, ob die automatische Dämpfung aktiviert ist oder nicht, im Energie-Dashboard visualisiert werden.

> [!NOTE]
>
> Solcast hat die API-Limits angepasst. Neu erstellte Hobbyisten-Konten erlauben maximal 10 API-Aufrufe pro Tag. Bestehende Hobbyisten behalten bis zu 50 Aufrufe pro Tag.

## Solcast-Anforderungen

Registrieren Sie sich für einen API-Schlüssel (https://solcast.com/).

> Solcast benötigt unter Umständen bis zu 24 Stunden, um das Konto zu erstellen.

Konfigurieren Sie Ihre Dachstandorte korrekt auf `solcast.com` .

Entfernen Sie alle Beispiel-Websites aus Ihrem Solcast-Dashboard (Beispiele für Beispiel-Websites und die Probleme, die auftreten können, wenn Sie diese nicht entfernen, finden Sie [unter Bekannte Probleme](#known-issues) ).

Kopieren Sie den API-Schlüssel zur Verwendung mit dieser Integration (siehe [Konfiguration](#Configuration) unten).

Achten Sie unbedingt auf die korrekte Konfiguration Ihres Solcast-Standorts. Nutzen Sie den Hinweis „Standortausrichtung“, um sicherzustellen, dass das Azimut korrekt vorzeichenbehaftet ist. Andernfalls werden die Vorhersagen verschoben angezeigt, möglicherweise um bis zu einer Stunde im Laufe des Tages.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png" width="600">

Der Azimut wird *nicht* als Wert von 0 bis 359 Grad angegeben, sondern als 0 bis 180 Grad für Westausrichtung bzw. 0 *bis* -179 Grad für Ostausrichtung. Dieser Wert gibt die Gradzahl des Winkels von Norden an, wobei das Vorzeichen West oder Ost ist. Im Zweifelsfall informieren Sie sich kurz.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png" width="300">

Eine altbewährte Methode, die funktionieren kann, ist folgende: Verwenden Sie ein nach Norden ausgerichtetes Satellitenbild Ihres Hauses in Google Maps und messen Sie den Azimut mit einem 180°-Winkelmesser aus Kunststoff. Richten Sie die gerade Kante des Winkelmessers in Nord-Süd-Richtung auf dem Bildschirm aus und legen Sie den Mittelpunkt an eine repräsentative Wandplatte. Zählen Sie die Grad von Norden weg. Für eine westliche oder östliche Ausrichtung drehen Sie den Winkelmesser um. Gegebenenfalls müssen Sie einen Screenshot des Kartenbildes als PNG/JPG-Datei erstellen und die Ausrichtung durch Hilfslinien korrigieren, um den Winkel genau messen zu können.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png" width="300">

Die Verwendung von Google Earth oder ChatGPT sind weitere Alternativen.

> [!NOTE]
>
> Solcast hat seinen Hauptsitz in Sydney, Australien, auf der Südhalbkugel und verwendet die Azimut-Nummerierung in Grad, die von Norden weg zeigen. Wenn Sie auf der Nordhalbkugel leben, verwenden Online-Kartendienste zur Azimutbestimmung wahrscheinlich eine Nummerierungskonvention, die Grad von *Süden* weg zeigt, was zu inkompatiblen Werten führt.
>
> Eine Solcast-Konfiguration mit einer Dachausrichtung von Nord/Nordost/Nordwest auf der Nordhalbkugel bzw. Süd/Südost/Südwest auf der Südhalbkugel wird als möglicherweise ungewöhnlich angesehen, da diese Ausrichtungen zu keiner Zeit direkt zur Sonne gerichtet sind.
>
> Beim Start überprüft die Integration Ihre Solcast-Azimut-Einstellung, um mögliche Fehlkonfigurationen aufzudecken. Bei einer ungewöhnlichen Dachausrichtung wird eine Warnmeldung im Home Assistant-Protokoll ausgegeben und ein Problem gemeldet. Sollten Sie diese Warnung erhalten und Ihre Solcast-Einstellungen als korrekt bestätigt haben, können Sie die Warnmeldung ignorieren. Sie dient lediglich dazu, Konfigurationsfehler zu erkennen.
>
> Es gibt immer wieder Ausreißer, beispielsweise zwei Dächer, die sowohl nach Westen als auch nach Osten ausgerichtet sind und auf denen die Paneele jeweils um 180 Grad versetzt installiert sind. Eine dieser Dachflächen gilt als „ungewöhnlich“. Überprüfen Sie den Azimut gemäß Solcast und beheben Sie das Problem oder ignorieren Sie die Warnung gegebenenfalls. Beachten Sie: 0° entspricht laut Solcast Norden; alle Ausrichtungen beziehen sich darauf.

## Installation

### HACS empfahl

*(Empfohlene Installationsmethode)*

Installieren Sie HACS als Standard-Repository. Weitere Informationen zu HACS finden Sie [hier](https://hacs.xyz/) . Falls Sie HACS noch nicht installiert haben, holen Sie dies bitte zuerst nach!

Die einfachste Möglichkeit zur Installation der Integration besteht darin, auf die Schaltfläche unten zu klicken, um diese Seite in Ihrer Home Assistant HACS-Seite zu öffnen (Sie werden nach Ihrer Home Assistant-URL gefragt, falls Sie diese Art von Schaltfläche noch nie verwendet haben).

[](https://my.home-assistant.io/redirect/hacs_repository/?owner=BJReplay&repository=ha-solcast-solar&category=integration)![Öffnen Sie Ihre Home Assistant-Instanz und öffnen Sie ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)

Sie werden aufgefordert, zu bestätigen, dass Sie das Repository innerhalb von HACS in Home Assistant öffnen möchten:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png">

Sie sehen nun diese Seite mit einem `↓ Download` Button unten rechts – klicken Sie darauf:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png">

Sie werden aufgefordert, die Solcast PV-Prognosekomponente herunterzuladen – klicken Sie auf `Download` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png">

Nach der Installation wird Ihnen wahrscheinlich eine Benachrichtigung in `Settings` angezeigt:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png">

Klicken Sie auf Einstellungen, und Sie sollten eine Reparaturbenachrichtigung mit dem Hinweis `Restart required` sehen:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png">

Falls Sie diese Meldung nicht sehen (möglicherweise verwenden Sie eine ältere Version von Home Assistant), gehen Sie zu `System` , `Settings` , klicken Sie auf das Stromsymbol und `Restart Home Assistant` . Sie müssen Home Assistant neu starten, bevor Sie die soeben heruntergeladene benutzerdefinierte Komponente „Solcast PV Forecast“ konfigurieren können.

Nach dem Neustart folgen Sie den Anweisungen unter [Konfiguration](#configuration) , um die Einrichtung der Solcast PV Forecast-Integrationskomponente fortzusetzen.

### Manuelle Installation in HACS

Mehr Infos [hier](https://hacs.xyz/docs/faq/custom_repositories/)

1. (Falls Sie es verwenden, entfernen Sie oziee/ha-solcast-solar in HACS)
2. Fügen Sie ein benutzerdefiniertes Repository hinzu (Menü mit drei vertikalen Punkten, oben rechts): `https://github.com/BJReplay/ha-solcast-solar` als `integration`
3. Suchen Sie in HACS nach „Solcast“, öffnen Sie es und klicken Sie auf die Schaltfläche `Download`
4. Siehe [Konfiguration](#configuration) unten

Wenn Sie zuvor Oziees ha-solcast-solar verwendet haben, sollten alle bisherigen Einstellungen und Konfigurationen erhalten bleiben.

### Manuelle Installation (ohne HACS)

Das sollten Sie wahrscheinlich **nicht** tun! Verwenden Sie die oben beschriebene HACS-Methode, es sei denn, Sie wissen genau, was Sie tun und haben einen guten Grund für die manuelle Installation.

1. Öffnen Sie mit dem Werkzeug Ihrer Wahl den Ordner (das Verzeichnis) für Ihre HA-Konfiguration (wo sich `configuration.yaml` befindet).
2. Falls dort kein Ordner namens `custom_components` vorhanden ist, müssen Sie ihn erstellen.
3. Erstellen Sie im Ordner `custom_components` einen neuen Ordner namens `solcast_solar`
4. Laden Sie *alle* Dateien aus dem Ordner `custom_components/solcast_solar/` in diesem Repository herunter.
5. Legen Sie die heruntergeladenen Dateien in den neu erstellten Ordner.
6. *Starten Sie HA neu, um die neue Integration zu laden.*
7. Siehe [Konfiguration](#configuration) unten

### Beta-Versionen

Möglicherweise sind Beta-Versionen verfügbar, die Probleme beheben.

Prüfen Sie unter https://github.com/BJReplay/ha-solcast-solar/releases, ob ein Problem bereits behoben wurde. Falls ja, aktivieren Sie die `Solcast PV Pre-release` um das Beta-Upgrade zu ermöglichen (oder aktivieren Sie bei HACS v1 `Show beta versions` “).

Wir freuen uns über Ihr Feedback aus den Beta-Tests in den Repository [-Diskussionen](https://github.com/BJReplay/ha-solcast-solar/discussions) , wo für jede aktive Beta-Version eine Diskussion stattfinden wird.

## Konfiguration

1. [Klicken Sie hier](https://my.home-assistant.io/redirect/config_flow_start/?domain=solcast_solar) , um direkt eine `Solcast Solar` Integration hinzuzufügen **oder**<br> a. Gehen Sie in Home Assistant zu Einstellungen -&gt; [Integrationen](https://my.home-assistant.io/redirect/integrations/)<br> b. Klicken Sie auf `+ Add Integrations`

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png">

und geben Sie `Solcast PV Forecast` ein, um die Solcast PV Forecast-Integration aufzurufen, und wählen Sie diese aus.<br>

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png">

1. Geben Sie Ihren `Solcast API Key` , `API limit` und die gewünschte automatische Aktualisierungsoption ein und klicken Sie auf `Submit` . Falls Sie mehrere Solcast-Konten besitzen, weil Sie mehr als zwei Dachinstallationen haben, geben Sie alle API-Schlüssel Ihrer Solcast-Konten durch Kommas getrennt ein `xxxxxxxx-xxxxx-xxxx,yyyyyyyy-yyyyy-yyyy` . ( *Hinweis: Die Verwendung mehrerer Konten kann gegen die Solcast-Nutzungsbedingungen verstoßen, wenn sich die Standorte dieser Konten in einem Umkreis von einem Kilometer (0,62 Meilen) befinden.* ) Ihr API-Limit beträgt 10 für neue Solcast-Nutzer bzw. 50 für Early Adopters. Wenn das API-Limit für mehrere Konten gleich ist, geben Sie entweder einen einzelnen Wert für alle Konten, beide Werte durch Kommas getrennt oder das niedrigste API-Limit aller Konten als einen einzelnen Wert ein. Informationen zur Konfiguration ausgeschlossener Standorte für die Verwendung mehrerer API-Schlüssel finden Sie unter [„Konfiguration ausgeschlossener Standorte“](#excluded-sites-configuration) .
2. Wenn keine automatische Aktualisierungsoption ausgewählt wurde, erstellen Sie Ihre eigene Automatisierung, um die Aktion `solcast_solar.update_forecasts` zu den Zeitpunkten aufzurufen, zu denen Sie die Solarprognose aktualisieren möchten.
3. Richten Sie die Einstellungen des Home Assistant Energy Dashboards ein.
4. Um nach der Installation weitere Konfigurationsoptionen zu ändern, wählen Sie die Integration unter `Devices & Services` und anschließend `CONFIGURE` aus.

Verwenden Sie unbedingt Ihren `API Key` und nicht Ihre in Solcast erstellte Dach-ID. Ihren API-Schlüssel finden Sie hier: [api key](https://toolkit.solcast.com.au/account) .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png" width="500">

> [!WICHTIG] Der API-Schlüssel und die zugehörigen Websites werden beim Speichern der Erstkonfiguration überprüft. Diese erste Überprüfung kann fehlschlagen, da die Solcast-API vorübergehend nicht verfügbar ist. Versuchen Sie in diesem Fall die Konfiguration einfach nach einigen Minuten erneut. Die Fehlermeldung gibt darüber Auskunft.

### Aktualisierung der Prognosen

Alle Websites müssen durch die Integration zum gleichen Zeitpunkt aktualisiert werden, daher wird bei einem abweichenden API-Schlüssellimit das niedrigste Limit aller konfigurierten Schlüssel verwendet.

> [!NOTE]
>
> Der Grund für die Verwendung des kleinsten Grenzwerts ist einfach, und eine alternative Lösung ist problematisch: Die prognostizierten Werte für jedes 30-Minuten-Intervall werden zur Gesamtprognose kombiniert, daher müssen alle Standorte für alle Intervalle berücksichtigt werden. (Man könnte versucht sein, die Intervalle anderer Standorte zu „interpolieren“, aber denken Sie daran, dass es sich um eine Prognose handelt. Pull-Anfragen werden berücksichtigt, sofern sie vollständige `pytest` Szenarien enthalten.)

#### Automatische Aktualisierung der Prognosen

Standardmäßig werden bei Neuinstallationen die Wettervorhersagen automatisch und planmäßig aktualisiert.

Die automatische Aktualisierung sorgt dafür, dass Wettervorhersagen bei Sonnenschein automatisch über die Stunden verteilt werden, alternativ auch über einen 24-Stunden-Zeitraum. Die Anzahl der täglichen Aktualisierungen wird anhand der Anzahl der Solcast-Dachstandorte und des konfigurierten API-Limits berechnet. Bei mehreren API-Schlüsseln wird die geringstmögliche Anzahl an Aktualisierungen für alle Standorte verwendet.

Soll ein Update außerhalb dieser Zeiten abgerufen werden, kann das API-Limit in der Integrationskonfiguration reduziert und eine Automatisierung eingerichtet werden, die die Aktion `solcast_solar.force_update_forecasts` zum gewünschten Zeitpunkt aufruft. (Beachten Sie, dass der Aufruf der Aktion `solcast_solar.update_forecasts` abgelehnt wird, wenn die automatische Aktualisierung aktiviert ist. Verwenden Sie in diesem Fall stattdessen die erzwungene Aktualisierung.)

Um beispielsweise direkt nach Mitternacht ein Update durchzuführen und die automatische Aktualisierung zu nutzen, erstellen Sie die gewünschte Automatisierung, die das Update erzwingt, und reduzieren Sie anschließend das in der Automatisierung konfigurierte API-Limit entsprechend. (Wenn der API-Schlüssel in diesem Beispiel zehn Aufrufe pro Tag und zwei Dachstandorte zulässt, reduzieren Sie das API-Limit auf acht, da bei der Ausführung der Automatisierung zwei Updates verwendet werden.)

Die Verwendung von „Force Update“ erhöht den API-Nutzungszähler nicht, was so beabsichtigt ist.

> [!NOTE] *Umstellung von der Automatisierung auf automatische Aktualisierung:*
>
> Wenn Sie derzeit die empfohlene Automatisierung nutzen, die Aktualisierungen relativ gleichmäßig zwischen Sonnenaufgang und Sonnenuntergang verteilt, sollte die Aktivierung der automatischen Aktualisierung von Sonnenaufgang bis Sonnenuntergang keine unerwarteten Fehler beim Abrufen von Vorhersagen aufgrund von API-Limitüberschreitungen verursachen. Die empfohlene Automatisierung ist nicht identisch mit der automatischen Aktualisierung, aber zeitlich sehr ähnlich.
>
> Wird ein reduziertes API-Limit implementiert und zusätzlich zu einer anderen Tageszeit (z. B. Mitternacht) ein erzwungenes Update durchgeführt, kann eine Anpassungsphase von 24 Stunden erforderlich sein. In dieser Zeit kann es vorkommen, dass eine API-Erschöpfung gemeldet wird, obwohl das tatsächliche Nutzungslimit der Solcast-API noch nicht erreicht ist. Diese Fehler werden innerhalb von 24 Stunden behoben.

#### Verwendung einer HA-Automatisierung zur Aktualisierung von Prognosen

Wenn die automatische Aktualisierung nicht aktiviert ist, erstellen Sie eine oder mehrere neue Automatisierungen und legen Sie die gewünschten Auslösezeiten für die Abfrage neuer Solcast-Vorhersagedaten fest. Verwenden Sie dazu die Aktion `solcast_solar.update_forecasts` . Beispiele sind vorhanden; passen Sie diese an Ihre Bedürfnisse an oder erstellen Sie eigene.

<details><summary><i>Klicken Sie hier, um die Beispiele anzuzeigen.</i><p></p></summary>
</details>

Um die täglich verfügbaren API-Aufrufe optimal zu nutzen, können Sie die Automatisierung so einstellen, dass sie die API in einem Intervall aufruft, das sich aus der Anzahl der Tagesstunden geteilt durch die Gesamtzahl der täglich möglichen API-Aufrufe ergibt.

Diese Automatisierung orientiert sich bei den Ausführungszeiten an Sonnenaufgang und Sonnenuntergang, die weltweit variieren, und verteilt so die Last auf Solcast. Das Verhalten ähnelt der automatischen Aktualisierung von Sonnenaufgang bis Sonnenuntergang, mit dem Unterschied, dass zusätzlich ein zufälliger Zeitversatz berücksichtigt wird. Dadurch soll die Wahrscheinlichkeit verringert werden, dass die Solcast-Server gleichzeitig von mehreren Anfragenden überlastet werden.

```yaml
alias: Solcast update
description: ""
triggers:
  - trigger: template
    value_template: >-
      {% set nr = as_datetime(state_attr('sun.sun','next_rising')) | as_local %}
      {% set ns = as_datetime(state_attr('sun.sun','next_setting')) | as_local %}
      {% set api_request_limit = 10 %}
      {% if nr > ns %}
        {% set nr = nr - timedelta(hours = 24) %}
      {% endif %}
      {% set hours_difference = (ns - nr) %}
      {% set interval_hours = hours_difference / api_request_limit %}
      {% set ns = namespace(match = false) %}
      {% for i in range(api_request_limit) %}
        {% set start_time = nr + (i * interval_hours) %}
        {% if ((start_time - timedelta(seconds=30)) <= now()) and (now() <= (start_time + timedelta(seconds=30))) %}
          {% set ns.match = true %}
        {% endif %}
      {% endfor %}
      {{ ns.match }}
conditions:
  - condition: sun
    before: sunset
    after: sunrise
actions:
  - delay:
      seconds: "{{ range(30, 360)|random|int }}"
  - action: solcast_solar.update_forecasts
    data: {}
mode: single
```

> [!NOTE]
>
> Wenn Sie zwei Arrays auf Ihrem Dach haben, werden für jede Aktualisierung zwei API-Aufrufe durchgeführt, wodurch sich die Anzahl der Aktualisierungen effektiv auf fünf pro Tag reduziert. Ändern Sie in diesem Fall Folgendes: `api_request_limit = 5`

Die nächste Automatisierung beinhaltet auch eine Randomisierung, damit Anrufe nicht genau gleichzeitig erfolgen und so hoffentlich vermieden wird, dass die Solcast-Server durch mehrere gleichzeitige Anrufe überlastet werden. Sie wird alle vier Stunden zwischen Sonnenaufgang und Sonnenuntergang ausgelöst:

```yaml
alias: Solcast_update
description: New API call Solcast
triggers:
 - trigger: time_pattern
   hours: /4
conditions:
 - condition: sun
   before: sunset
   after: sunrise
actions:
 - delay:
     seconds: "{{ range(30, 360)|random|int }}"
 - action: solcast_solar.update_forecasts
   data: {}
mode: single
```

Die nächste Automatisierung wird um 4 Uhr morgens, 10 Uhr morgens und 16 Uhr nachmittags mit einer zufälligen Verzögerung ausgelöst.

```yaml
alias: Solcast update
description: ""
triggers:
  - trigger: time
    at:
      - "4:00:00"
      - "10:00:00"
      - "16:00:00"
conditions: []
actions:
  - delay:
      seconds: "{{ range(30, 360)|random|int }}"
  - action: solcast_solar.update_forecasts
    data: {}
mode: single
```




> [!TIP]
>
> Die Solcast-Server scheinen gelegentlich überlastet zu sein und geben in diesen Fällen den Fehlercode 429 (Zu ausgelastet) zurück. Die Integration pausiert automatisch und versucht die Verbindung mehrmals erneut herzustellen, doch auch diese Strategie kann gelegentlich zum Fehlschlagen beim Herunterladen der Wettervorhersagedaten führen.
>
> Das Ändern Ihres API-Schlüssels ist keine Lösung, ebenso wenig wie die Deinstallation und Neuinstallation der Integration. Diese „Tricks“ mögen zwar kurzfristig funktionieren, tatsächlich haben Sie es aber lediglich später erneut versucht, und die Integration funktioniert nun, da die Solcast-Server weniger ausgelastet sind.
>
> Um herauszufinden, ob dies Ihr Problem ist, sehen Sie sich die Home Assistant-Protokolle an. Für detaillierte Informationen (die beim Melden eines Problems erforderlich sind) stellen Sie sicher, dass die Debug-Protokollierung aktiviert ist.
>
> Anweisungen zur Protokollerfassung finden Sie in der Vorlage für Fehlerberichte – diese werden Ihnen angezeigt, wenn Sie einen neuen Fehlerbericht erstellen. Stellen Sie sicher, dass Sie diese Protokolle beifügen, wenn Sie die Unterstützung der Repository-Mitwirkenden in Anspruch nehmen möchten.
>
> Unten sehen Sie ein Beispiel für Meldungen über belegtes System und einen erfolgreichen Wiederholungsversuch (mit aktiviertem Debug-Logging). In diesem Fall liegt kein Problem vor, da der Wiederholungsversuch erfolgreich war. Sollten zehn aufeinanderfolgende Versuche fehlschlagen, wird der Abruf der Prognose mit einem `ERROR` beendet. In diesem Fall lösen Sie manuell eine weitere `solcast_solar.update_forecasts` -Aktion aus (oder verwenden Sie bei aktivierter automatischer Aktualisierung `solcast_solar.force_update_forecasts` ) oder warten Sie auf die nächste geplante Aktualisierung.
>
> Wenn beim Start der Integration die Daten der Websites geladen werden und der Aufruf mit dem Fehlercode 429 (Zu ausgelastet) fehlschlägt, startet die Integration, sofern die Websites zuvor zwischengespeichert wurden, und verwendet diese zwischengespeicherten Informationen. Wurden Änderungen an den Websites vorgenommen, werden diese in diesem Fall nicht berücksichtigt, was zu unerwarteten Ergebnissen führen kann. Überprüfen Sie bei unerwarteten Problemen das Protokoll. Ein Neustart behebt das Problem in der Regel und liest die aktualisierten Websites korrekt ein.

```
INFO (MainThread) [custom_components.solcast_solar.solcastapi] Getting forecast update for site 1234-5678-9012-3456
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Polling API for site 1234-5678-9012-3456
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetch data url - https://api.solcast.com.au/rooftop_sites/1234-5678-9012-3456/forecasts
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetching forecast
WARNING (MainThread) [custom_components.solcast_solar.solcastapi] Solcast API is busy, pausing 55 seconds before retry
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetching forecast
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] API returned data. API Counter incremented from 35 to 36
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Writing usage cache
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] HTTP session returned data type <class 'dict'>
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] HTTP session status is 200/Success
```

### HA-Energie-Dashboard-Einstellungen einrichten

Gehen Sie zu `Settings` , `Dashboards` , `Energy` und klicken Sie auf das Stiftsymbol, um Ihre Energie-Dashboard-Konfiguration zu bearbeiten.

Die Solarprognose muss mit einem Solarstromerzeugungselement in Ihrem Energie-Dashboard verknüpft sein.

Bearbeiten Sie ein `Solar Panels` `Solar production` , das Sie zuvor erstellt haben (oder jetzt erstellen werden). Fügen Sie kein separates `Solar production` hinzu, da dies zu unerwarteten Ergebnissen führt.

Es kann nur eine einzige Konfiguration der gesamten Solcast PV-Prognose im Energie-Dashboard geben, die alle Standorte (Anlagen) Ihres Solcast-Kontos abdeckt. Es ist nicht möglich, die Prognose im Energie-Dashboard für verschiedene Solaranlagen/Solcast-Standorte aufzuteilen.

> [!IMPORTANT]<br> Wenn Ihr System keinen Solarstromsensor besitzt, funktioniert diese Integration im Energie-Dashboard nicht. Die grafische Darstellung und die Prognosefunktion setzen die Einrichtung eines Solarstromsensors voraus.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png" width="500">

Wählen Sie im Abschnitt `Solar production forecast` die Option `Forecast Production` und anschließend „ `Solcast Solar` . Klicken Sie auf `Save` , und Home Assistant erledigt den Rest.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

## Interaktion

Die Integration stellt zahlreiche Aktionen, Sensoren und Konfigurationselemente sowie viele Sensorattribute bereit, die aktiviert werden können.

Nutzen Sie die `Developer tools` von Home Assistant, um die verfügbaren Attribute zu untersuchen, da deren Benennung größtenteils von der jeweiligen Bereitstellung abhängt. Beispiele zur Verwendung dieser Attribute finden Sie an anderer Stelle in dieser Readme-Datei.

Außerdem gibt es eine Sammlung von Jinja2-Vorlagen unter https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md, die Beispiele für grundlegende, fortgeschrittene und professionelle Vorlagen enthält.

### Sensoren

Allen Sensornamen steht der Integrationsname `Solcast PV Forecast` vorangestellt.

Name | Typ | Attribute | Einheit | Beschreibung
--- | --- | --- | --- | ---
`Forecast Today` | Nummer | Y | `kWh` | Prognostizierte Solarstromproduktion für heute.
`Forecast Tomorrow` | Nummer | Y | `kWh` | Prognostizierte Gesamtproduktion von Solarstrom für Tag + 1 (morgen).
`Forecast Day 3` | Nummer | Y | `kWh` | Prognostizierte Gesamtsolarproduktion für Tag + 2 (Tag 3 ist standardmäßig deaktiviert).
`Forecast Day 4` | Nummer | Y | `kWh` | Prognostizierte Gesamtsolarproduktion für Tag + 3 (Tag 4 ist standardmäßig deaktiviert).
`Forecast Day 5` | Nummer | Y | `kWh` | Prognostizierte Gesamtproduktion von Solarstrom für Tag + 4 (Tag 5 ist standardmäßig deaktiviert).
`Forecast Day 6` | Nummer | Y | `kWh` | Prognostizierte Gesamtsolarproduktion für Tag + 5 (Tag 6 ist standardmäßig deaktiviert).
`Forecast Day 7` | Nummer | Y | `kWh` | Prognostizierte Gesamtproduktion von Solarstrom für Tag + 6 (Tag 7 ist standardmäßig deaktiviert).
`Forecast This Hour` | Nummer | Y | `Wh` | Prognostizierte Solarstromproduktion zur aktuellen Stunde (Attribute enthalten Standortaufschlüsselung).
`Forecast Next Hour` | Nummer | Y | `Wh` | Prognostizierte Solarstromproduktion der nächsten Stunde (Attribute enthalten Standortaufschlüsselung).
`Forecast Next X Hours` | Nummer | Y | `Wh` | Benutzerdefinierte Prognose der Solarstromproduktion für die nächsten X Stunden, standardmäßig deaktiviert<br> Hinweis: Diese Vorhersage beginnt zur aktuellen Zeit und ist nicht stündlich ausgerichtet wie etwa „Diese Stunde“, „Nächste Stunde“.
`Forecast Remaining Today` | Nummer | Y | `kWh` | Prognostizierte verbleibende Solarstromproduktion heute.
`Peak Forecast Today` | Nummer | Y | `W` | Höchste prognostizierte Produktion innerhalb einer Stunde heute (Attribute enthalten Standortaufschlüsselung).
`Peak Time Today` | Datum/Uhrzeit | Y |  | Stunde der heute prognostizierten maximalen Solarstromproduktion (Attribute enthalten Standortaufschlüsselung).
`Peak Forecast Tomorrow` | Nummer | Y | `W` | Höchste prognostizierte Produktion innerhalb einer Stunde morgen (Attribute enthalten Standortaufschlüsselung).
`Peak Time Tomorrow` | Datum/Uhrzeit | Y |  | Stunde der maximalen prognostizierten Solarstromproduktion morgen (Attribute enthalten Standortaufschlüsselung).
`Forecast Power Now` | Nummer | Y | `W` | Prognostizierte nominale Solarstromerzeugung zum jetzigen Zeitpunkt (Attribute enthalten Standortaufschlüsselung).
`Forecast Power in 30 Minutes` | Nummer | Y | `W` | Prognostizierte nominale Solarleistung in 30 Minuten (Attribute enthalten Standortaufschlüsselung).
`Forecast Power in 1 Hour` | Nummer | Y | `W` | Prognostizierte nominale Solarleistung in 1 Stunde (Attribute enthalten Standortaufschlüsselung).

> [!NOTE]
>
> Sofern eine Standortaufschlüsselung als Attribut verfügbar ist, lautet der Attributname die Solcast-Standortressourcen-ID (wobei Bindestriche durch Unterstriche ersetzt werden).
>
> Die meisten Sensoren enthalten außerdem ein Attribut für `estimate` , `estimate10` und `estimate90` . Es können Vorlagensensoren erstellt werden, um deren Wert zugänglich zu machen, oder die `state_attr()` kann direkt in Automatisierungen verwendet werden.
>
> Diese können Sie in einem Vorlagensensor oder einer Automatisierung beispielsweise so erreichen:
>
> ```
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', '1234_5678_9012_3456') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10_1234_5678_9012_3456') | float(0) }}
> ```
>
> Siehe auch das unten stehende Beispiel-PV-Diagramm, um zu sehen, wie Prognosedetails aus dem Attribut „detaillierte Prognose“ grafisch dargestellt werden können.

> [!NOTE]
>
> Die Werte für `Next Hour` und `Forecast Next X Hours` können unterschiedlich sein, wenn die benutzerdefinierte Einstellung für X Stunden auf 1 gesetzt ist. Dafür gibt es eine einfache Erklärung.
>
> Sie werden anhand unterschiedlicher Start- und Endzeiten berechnet. Die eine Berechnung beginnt mit dem Beginn der aktuellen Stunde, also in der Vergangenheit, z. B. von 14:00:00 bis 15:00:00. Der benutzerdefinierte Sensor arbeitet ab „jetzt“ in Fünf-Minuten-Intervallen, z. B. von 14:20:00 bis 15:20:00, und verwendet dabei interpolierte Werte.
>
> Das Ergebnis wird wahrscheinlich je nach Zeitpunkt der Wertabfrage variieren, ist also nicht falsch. Es ist einfach nur anders.

### Attribute

Wie bereits erwähnt, werden Sensorattribute erstellt, um die Verwendung von Sensorstatusvarianten in Vorlagen zu ermöglichen. Beispiele hierfür sind die Schätzungssicherheit, `estimate10` / `estimate` / `estimate90` . Der *Sensorstatus* ist standardmäßig auf `estimate` eingestellt. Es kann jedoch gewünscht sein, das zehnte Perzentil eines Sensors in einem Dashboard anzuzeigen. Dies wird durch die Verwendung von *Attributwerten* ermöglicht.

Einige Attributnamen sind umgebungsspezifisch (Beispiele finden Sie hier), und einige Attribute sind standardmäßig oder auf Benutzerwunsch deaktiviert, um die Übersichtlichkeit zu verbessern. Diese Einstellungen werden im Dialogfeld `CONFIGURE` vorgenommen.

Attributnamen dürfen keinen Bindestrich enthalten. Solcast-Site-Ressourcen-IDs *werden* mit einem Bindestrich benannt; daher werden Bindestriche durch Unterstriche ersetzt, wenn ein Attribut nach der Site-Ressourcen-ID benannt ist, die es repräsentiert.

Alle detaillierten Prognosesensoren, die stündliche oder halbstündliche Aufschlüsselungen liefern, geben (ebenso wie die zugrunde liegenden Solcast-Daten) Daten in kW an – es handelt sich um Leistungssensoren, nicht um Energiesensoren, und sie stellen die durchschnittliche Leistungsprognose für den Zeitraum dar.

Für alle Sensoren:

- `estimate10` : 10. Perzentil des Prognosewerts (Zahl)
- `estimate` : 50. Perzentil des Prognosewerts (Anzahl)
- `estimate90` : 90. Perzentil des Prognosewerts (Zahl)
- `1234_5678_9012_3456` : Ein einzelner Standortwert, d. h. ein Teil der Gesamtzahl
- `estimate10_1234_5678_9012_3456` : 10. Wert (Nummer) für einen einzelnen Standort
- `estimate_1234_5678_9012_3456` : 50. Wert (Nummer) eines einzelnen Standorts
- `estimate90_1234_5678_9012_3456` : 90. Wert (Nummer) für einen einzelnen Standort

Nur für den Sensor `Forecast Next X Hours` :

- `custom_hours` : Die vom Sensor gemeldete Stundenzahl (Zahl)

Nur für Sensoren zur täglichen Wettervorhersage:

- `detailedForecast` : Eine halbstündliche Aufschlüsselung der erwarteten durchschnittlichen Stromerzeugung für jedes Intervall (Liste von Dictionaries, Einheiten in kW, nicht kWh), und falls die automatische Dämpfung aktiv ist, wird auch der für jedes Intervall ermittelte Faktor angegeben.
- `detailedHourly` : Eine stündliche Aufschlüsselung der erwarteten durchschnittlichen Stromerzeugung für jedes Intervall (Liste von Dictionaries, Einheiten in kW)
- `detailedForecast_1234_5678_9012_3456` : Eine halbstündliche, standortspezifische Aufschlüsselung der erwarteten durchschnittlichen Stromerzeugung für jedes Intervall (Liste von Dictionaries, Einheiten in kW)
- `detailedHourly_1234_5678_9012_3456` : Eine stündliche, standortspezifische Aufschlüsselung der erwarteten durchschnittlichen Stromerzeugung für jedes Intervall (Liste von Dictionaries, Einheiten in kW)

Die „Liste der Dictionaries“ hat folgendes Format, wobei Beispielwerte verwendet werden: (Beachten Sie die Inkonsistenz zwischen `pv_estimateXX` und `estimateXX` die an anderer Stelle verwendet wird. Dies ist auf frühere Vorgehensweisen zurückzuführen.)

JSON:

```json
[
  {
    "period_start": "2025-04-06T08:00:00+10:00",
    "dampening_factor": 0.888, <== for detailedForecast only, and only if automated dampening is enabled
    "pv_estimate10": 10.000,
    "pv_estimate": 50.000,
    "pv_estimate90": 90.000
  },
  ...
]
```

YAML:

```yaml
- period_start: '2025-04-06T08:00:00+10:00'
  dampening_factor: 0.888, <== for detailedForecast only, and only if automated dampening is enabled
  pv_estimate10: 10.000
  pv_estimate: 50.000
  pv_estimate90: 90.000
- ...
```

### Aktionen

Aktion | Beschreibung
--- | ---
`solcast_solar.update_forecasts` | Wettervorhersagedaten aktualisieren (wird abgelehnt, wenn die automatische Aktualisierung aktiviert ist).
`solcast_solar.force_update_forecasts` | Aktualisiert die Prognosedaten zwangsweise (führt eine Aktualisierung unabhängig von der API-Nutzungsverfolgung oder der Einstellung für automatische Aktualisierung durch und erhöht den API-Nutzungszähler nicht; wird verweigert, wenn die automatische Aktualisierung nicht aktiviert ist).
`solcast_solar.force_update_estimates` | Aktualisierung der geschätzten Ist-Daten erzwingen (erhöht nicht den API-Nutzungszähler; wird verweigert, wenn „Geschätzte Ist-Werte abrufen“ nicht aktiviert ist).
`solcast_solar.clear_all_solcast_data` | Löscht zwischengespeicherte Daten und startet einen sofortigen Abruf neuer vergangener Ist- und Prognosewerte.
`solcast_solar.query_forecast_data` | Gibt eine Liste von Prognosedaten unter Verwendung eines Datums-/Zeitbereichs (Start - Ende) zurück.
`solcast_solar.query_estimate_data` | Gibt eine Liste geschätzter Ist-Daten unter Verwendung eines Datums-/Zeitbereichs (Start - Ende) zurück.
`solcast_solar.set_dampening` | Aktualisieren Sie die Dämpfungsfaktoren.
`solcast_solar.get_dampening` | Ermitteln Sie die aktuell eingestellten Dämpfungsfaktoren.
`solcast_solar.set_hard_limit` | Legen Sie eine harte Obergrenze für die Wechselrichterprognose fest.
`solcast_solar.remove_hard_limit` | Entfernen Sie die harte Obergrenze der Wechselrichterprognose.

Hier finden Sie Beispielparameter für jede `query` , `set` und `get` -Aktion. Verwenden Sie `Developer tools` | `Actions` , um die verfügbaren Parameter mit einer Beschreibung anzuzeigen.

Wenn ein „Site“-Parameter benötigt wird, verwenden Sie die Solcast-Site-Ressourcen-ID und nicht den Site-Namen.

```yaml
action: solcast_solar.query_forecast_data
data:
  start_date_time: 2024-10-06T00:00:00.000Z
  end_date_time: 2024-10-06T10:00:00.000Z
  undampened: false (optional)
  site: 1234-5678-9012-3456 (optional)
```

```yaml
action: solcast_solar.query_estimate_data
data:
  start_date_time: 2024-10-06T00:00:00.000Z
  end_date_time: 2024-10-06T10:00:00.000Z
```

```yaml
action: solcast_solar.set_dampening
data:
  damp_factor: 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
  site: 1234-5678-9012-3456 (optional)
```

```yaml
action: solcast_solar.set_hard_limit
data:
  hard_limit: 6
```

```yaml
action: solcast_solar.get_dampening
data:
  site: 1234-5678-9012-3456 (optional)
```

### Konfiguration

Name | Typ | Beschreibung
--- | --- | ---
`Forecast Field` | Wähler | Wählen Sie für die Sensorzustände die Prognosegenauigkeit „estimate“, „estimate10“ oder „estimate90“ aus.

### Diagnostik

Alle Namen der Diagnosesensoren beginnen mit `Solcast PV Forecast` außer beim `Rooftop site name` .

Name | Typ | Attribute | Einheit | Beschreibung
--- | --- | --- | --- | ---
`API Last Polled` | Datum/Uhrzeit | Y | `datetime` | Datum/Uhrzeit der letzten erfolgreichen Aktualisierung der Vorhersage.
`API Limit` | Nummer | N | `integer` | Gesamtzahl der API-Aufrufe innerhalb eines 24-Stunden-Zeitraums[^1].
`API used` | Nummer | N | `integer` | Gesamtzahl der API-Aufrufe heute (der API-Zähler wird um Mitternacht UTC auf Null zurückgesetzt)[^1].
`Dampening` | boolescher Wert | Y | `bool` | Ob die Dämpfung aktiviert ist (standardmäßig deaktiviert).
`Hard Limit Set` | Nummer | N | `float` oder `bool` | `False` , falls nicht gesetzt, ansonsten Wert in `kilowatts` .
`Hard Limit Set ******AaBbCc` | Nummer | N | `float` | Individuelles Leistungslimit. Wert in `kilowatts` .
`Rooftop site name` | Nummer | Y | `kWh` | Gesamtprognose für Dachterrassen heute (Attribute enthalten die Standortkonfiguration)[^2].

Zu `API Last Polled` gehören folgende:

- `failure_count_today` : Die Anzahl der Fehler (wie `429/Too busy` ), die seit Mitternacht Ortszeit aufgetreten sind.
- `failure_count_7_day` : Die Anzahl der Ausfälle, die in den letzten sieben Tagen aufgetreten sind.
- `last_attempt` : Datum und Uhrzeit des letzten Versuchs, die Prognose zu aktualisieren. „Aktuell einwandfrei“ bedeutet, dass die letzte Abfrage mindestens dem letzten Versuch entsprach.

Wenn die automatische Aktualisierung aktiviert ist, enthält die zuletzt abgefragte Datei auch die folgenden Attribute:

- `auto_update_divisions` : Die Anzahl der konfigurierten automatischen Aktualisierungen pro Tag.
- `auto_update_queue` : Es befinden sich derzeit maximal 48 zukünftige automatische Aktualisierungen in der Warteschlange.
- `next_auto_update` : Datum/Uhrzeit des nächsten geplanten automatischen Updates.

Wenn die Dämpfung aktiv ist, weist der Dämpfungssensor außerdem folgende Eigenschaften auf:

- `integration_automated` : Boolescher Wert. Gibt an, ob die automatische Dämpfung aktiviert ist.
- `last_updated` : Datum/Uhrzeit. Datum und Uhrzeit der letzten Einstellung der Dämpfungsfaktoren.
- `factors` : Dict. Das `interval` Startstunde:Minute und `factor` als Gleitkommazahl.

Beispielhafte Eigenschaften eines Dämpfungssensors:

```yaml
integration_automated: true
last_updated: 2025-08-26T04:03:01+00:00
factors:
- interval: '00:00'
  factor: 1
- interval: '00:30'
  factor: 1
- interval: '01:00'
  factor: 1
...
```

Zu den Attributen `Rooftop site name` gehören:

- `azimuth` / `tilt` : Ausrichtung des Panels.
- `capacity` : Standortkapazität in Wechselstrom.
- `capacity_dc` : Standortkapazität in Gleichstrom.
- `install_date` : Konfiguriertes Installationsdatum.
- `loss_factor` : Konfigurierter "Verlustfaktor".
- `name` : Der auf solcast.com konfigurierte Name der Website.
- `resource_id` : Die Ressourcen-ID der Website.
- `tags` : Die für den Dachterrassenstandort festgelegten Tags.

> [!NOTE]
>
> Breitengrad und Längengrad werden aus Datenschutzgründen absichtlich nicht in die Attribute des Dachstandorts aufgenommen.

[^1]: Die API-Nutzungsinformationen werden intern erfasst und stimmen möglicherweise nicht mit der tatsächlichen Kontonutzung überein.

[^2]: Jedes in Solcast erstellte Dach wird separat aufgelistet.

## Erweiterte Konfiguration

### Dämpfungskonfiguration

Die Dämpfungswerte berücksichtigen die Verschattung und passen die prognostizierte Stromerzeugung an. Die Dämpfung kann automatisch oder außerhalb der Integration ermittelt und per Serviceaktion festgelegt werden.

Änderungen der Dämpfungsfaktoren werden auf zukünftige Vorhersagen (einschließlich der Vorhersage für den aktuellen Tag) angewendet. Die Vorhersagehistorie behält die zum jeweiligen Zeitpunkt geltende Dämpfung bei.

Die automatische Dämpfung (siehe unten) berechnet die Gesamtdämpfungsfaktoren für alle Dachflächen. Soll die Dämpfung standortspezifisch erfolgen, kann dies mit einer eigenen Dämpfungslösung modelliert und die Faktoren anschließend mit der Aktion `solcast_solar.set_dampening` festgelegt werden. Siehe dazu auch [„Granulare Dämpfung“](#granular-dampening) weiter unten.

> [!NOTE]
>
> Wenn die automatische Dämpfung aktiviert ist, können die Dämpfungsfaktoren weder über eine Serviceaktion noch manuell in den Integrationsoptionen noch durch Schreiben der Datei `solcast-dampening.json` festgelegt werden.
>
> (Wird versucht, die Dämpfungsdatei mit der entsprechenden Schreibmethode zu schreiben, wird der Inhalt der neuen Datei ignoriert und später mit den aktualisierten automatischen Dämpfungsfaktoren überschrieben, sobald diese modelliert werden.)

#### Automatische Dämpfung

Ein Merkmal der Integration ist die automatische Dämpfung, bei der die tatsächliche Erzeugungshistorie mit der geschätzten historischen Erzeugung verglichen wird, um regelmäßig auftretende Erzeugungsanomalien zu ermitteln. Dies ist hilfreich, um Perioden mit wahrscheinlicher Verschattung der Solarmodule zu identifizieren und anschließend automatisch einen Dämpfungsfaktor für prognostizierte, voraussichtlich verschattete Tageszeiträume anzuwenden, wodurch die prognostizierte Energiemenge entsprechend reduziert wird.

Die automatische Dämpfung ist dynamisch und nutzt bis zu 14 gleitende Tage an Erzeugungs- und Schätzdaten, um ein Modell zu erstellen und die anzuwendenden Dämpfungsfaktoren zu bestimmen. Es werden maximal 14 Tage berücksichtigt. Bei der Aktivierung der Funktion kann eine Begrenzung der historischen Datenmenge zunächst zu einem kleineren Datensatz führen, dieser wird jedoch im Laufe der Zeit auf 14 Tage erweitert und die Modellierung verbessern.

Die automatische Dämpfung wendet auf Basis der gesamten Standortgenerierung und der Solcast-Daten die gleichen Dämpfungsfaktoren auf alle Dachstandorte an.

> [!NOTE]
>
> Die automatische Dämpfung ist möglicherweise nicht für Sie geeignet, insbesondere aufgrund der Art und Weise, wie Ihre Energieerzeuger den Energieverbrauch melden, oder wenn Sie einen Großhandelsenergietarif nutzen, bei dem die Preise negativ werden können und Sie daher die Einspeisung Ihres Stroms in diesen Zeiten begrenzen. (Lesen Sie aber weiter, um eine mögliche Lösung in diesem Bereich zu finden.)
>
> Diese integrierte automatische Dämpfungsfunktion wird vielen Anwendern zusagen, ist aber kein Allheilmittel.
>
> Es mag wie eine einfache Konfigurationsoption aussehen, ist es aber nicht. Es handelt sich um einen komplexen Code, der verschiedene Arten der PV-Erzeugungsmeldung und mögliche Kommunikationsprobleme zwischen Wechselrichter und Home Assistant verarbeiten und gleichzeitig durch Verschattung verursachte Erzeugungsanomalien erkennen muss.
>
> Wenn Sie vermuten, dass die automatische Dämpfung nicht ordnungsgemäß funktioniert, gehen Sie bitte folgendermaßen vor: DENKEN SIE NACH, UNTERSUCHEN SIE DIES UND MELDEN SIE anschließend alle Probleme mit der automatischen Dämpfung – in dieser Reihenfolge. Beschreiben Sie in Ihrem Problembericht detailliert, warum die automatische Dämpfung Ihrer Meinung nach nicht funktioniert und welche Lösungsmöglichkeiten es gibt.
>
> Sollten Sie bei der Untersuchung feststellen, dass ein Problem durch Ihre selbst entwickelte Generierungseinheit verursacht wird, ist die automatische Dämpfung möglicherweise nicht die richtige Lösung. In diesem Fall entwickeln Sie bitte Ihre eigene Dämpfungslösung oder geben Sie konstruktive Verbesserungsvorschläge. Die Komponenten für den Eigenbau mit Hilfe von Granulatdämpfung sind verfügbar.
>
> Sehen Sie sich auch die „erweiterten Optionen“ der Integration an. Es gibt viele Einstellmöglichkeiten für die automatische Dämpfung, die Ihr Problem möglicherweise lösen.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png" width="500">

Das Funktionsprinzip ist einfach und basiert auf zwei Haupteingaben sowie einer optionalen dritten.

##### Funktionsweise

Die automatische Dämpfung erstellt zunächst einen möglichst konsistenten Satz von (mehr als einer) halbstündlich [geschätzten tatsächlichen](https://github.com/BJReplay/ha-solcast-solar/issues/373#key-input-estimated-actual-data-from-solcast) Erzeugungsperioden aus den letzten vierzehn Tagen. (Dies ist nicht die tatsächliche Erzeugung vor Ort, sondern eine bestmögliche Schätzung von Solcast darüber, was hätte erzeugt werden sollen).

Anschließend wird dieser Wert mit den [historischen Erzeugungsdaten](#key-input-actual-pv-generation-for-your-site) für diese Zeiträume verglichen (ausgenommen Erzeugungszeiträume, in denen die Exportgrenzen durch [optionale Exportbegrenzungen](#optional-input-site-export-to-the-grid-combined-with-a-limit-value) erreicht wurden oder in denen die Einspeisung absichtlich unterdrückt wurde). Der höchste tatsächliche Erzeugungswert wird aus den vergleichbaren, bestgeschätzten tatsächlichen Werten ausgewählt, jedoch nur, wenn mehrere Erzeugungswerte vorliegen. Dieser Wert gibt Aufschluss darüber, ob externe Faktoren die Erzeugung beeinflussen, und dient zur Berechnung eines Basis-Dämpfungsfaktors.

Da die automatische Dämpfung erkennt, wann Verschattung Ihre Solarstromerzeugung beeinträchtigt, werden Tage mit „nicht optimal geschätzter PV-Erzeugung“ verworfen. Dies sind Tage, an denen die PV-Erzeugung aufgrund von Bewölkung, Regen usw. reduziert ist.

Anders ausgedrückt, und in einfachem Deutsch: Solcast schätzte in der Vergangenheit, dass die Produktion an sonnigen Tagen zu einem bestimmten Zeitpunkt durchschnittlich X kW betragen sollte. Tatsächlich wurden in letzter Zeit jedoch maximal Y kW erreicht. Daher werden die zukünftigen Prognosen im Zuge der Integration auf Y angepasst. Oder noch einfacher: Die geschätzte tatsächliche Erzeugung ist durchgehend höher als die maximal erreichbare, daher wird die Prognose entsprechend reduziert.

Da die Prognosezeiträume aufgrund der Bewölkung von den besten Schätzungen abweichen, wird der Basisfaktor vor seiner Anwendung auf die Prognosen mittels einer logarithmischen Differenzberechnung angepasst. Weicht die prognostizierte Solarstromerzeugung deutlich von der besten Schätzung ab, die zur Bestimmung des Basisdämpfungsfaktors verwendet wurde, wird dieser so angepasst, dass er nur noch geringe Auswirkungen hat (d. h. näher an einen Faktor von 1,0). Diese Anpassung erfolgt auf Grundlage des Wertes jedes Prognoseintervalls, sodass an jedem Tag wahrscheinlich unterschiedliche Faktoren angewendet werden.

Die Anpassung des Basisdämpfungsfaktors erfolgt, da eine signifikante Abweichung der prognostizierten Stromerzeugung in einem Intervall im Vergleich zu früheren, ertragreicheren Intervallen auf eine zu erwartende Periode mit starker Bewölkung hindeutet. Dadurch wird die Dämpfung an bewölkte Perioden angepasst, in denen diffuses Licht den größten Anteil der Solarstromerzeugung ausmacht und nicht das direkte Sonnenlicht, das am stärksten von Schatten beeinflusst wird.

> [!TIP]
>
> Untersuchen Sie das Attribut `detailedForecast` für jede Tagesvorhersage, um die automatisch auf jedes Intervall angewendeten Dämpfungsfaktoren zu sehen. Ein Beispieldiagramm in Apex finden Sie in der Datei [`TEMPLATES.md`](https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md) , das die praktische Anwendung dieser Dämpfungsinformationen veranschaulicht.

##### Wichtigste Eingangsgröße: Geschätzte Ist-Daten von Solcast

Neben Prognosen schätzt der Solcast-Dienst auch die wahrscheinliche tatsächliche CO₂-Produktion der Vergangenheit für jeden Dachstandort im Tagesverlauf. Grundlage hierfür sind hochauflösende Satellitenbilder, Wetterbeobachtungen und die Luftqualität (Wasserdampf/Smog). Diese Daten werden als „geschätzte tatsächliche CO₂-Produktion“ bezeichnet und sind für den jeweiligen Standort in der Regel recht genau.

Um geschätzte Ist-Daten zu erhalten, ist ein API-Aufruf erforderlich, der das API-Kontingent für Hobbyanwender aufbraucht. Berücksichtigen Sie den API-Aufrufverbrauch bei der Nutzung der automatischen Dämpfung. Pro konfigurierter Solcast-Dachstation und API-Schlüssel wird ein Aufruf pro Tag verwendet. (Reduzieren Sie das API-Limit für Prognoseaktualisierungen in den Optionen um eins für eine einzelne Dachstation oder um zwei für zwei Stationen.)

Die geschätzten Ist-Werte der Vergangenheit werden täglich kurz nach Mitternacht Ortszeit abgerufen und innerhalb von 15 Minuten aktualisiert. Ist die automatische Dämpfung aktiviert, werden die neuen Dämpfungsfaktoren für den kommenden Tag unmittelbar nach der Aktualisierung der geschätzten Ist-Werte modelliert. Alternativ kann eine Aktualisierung der geschätzten Ist-Werte manuell erzwungen werden; dabei werden gegebenenfalls auch die Dämpfungsfaktoren modelliert.

> [!TIP]
>
> Wenn Sie im Laufe des Tages möglichst viele Wettervorhersageaktualisierungen erhalten möchten, ist die Verwendung von geschätzten Istwerten und automatischer Dämpfung nicht geeignet. Dadurch verringert sich die Anzahl der möglichen Wettervorhersageaktualisierungen.

##### Wichtigste Eingabe: Tatsächliche PV-Erzeugung für Ihren Standort

Die Stromerzeugung wird aus den historischen Daten eines oder mehrerer Sensoren ermittelt. Eine einzelne PV-Wechselrichteranlage verfügt in der Regel über einen Sensor, der die Gesamtstromerzeugung misst und einen Wert für die PV-Erzeugung bzw. den PV-Export liefert ( *nicht* die Einspeisung ins Netz, sondern die vom Dach erzeugte Solarenergie). Mehrere Wechselrichter liefern jeweils einen eigenen Wert, und die Daten aller Sensoren werden anschließend für alle Dächer summiert.

Es muss ein oder mehrere Sensoren zur Messung des steigenden Energieverbrauchs bereitgestellt werden. Dieser Sensor kann sich um Mitternacht zurücksetzen oder als „kontinuierlich steigender“ Sensor arbeiten; wichtig ist, dass der Energieverbrauch den ganzen Tag über ansteigt.

Die Integration ermittelt die Einheiten anhand des Attributs `unit_of_measurement` und passt die Werte entsprechend an. Ist dieses Attribut nicht gesetzt, wird von kWh ausgegangen. Aktualisierungen der Erzeugungshistorie erfolgen um Mitternacht Ortszeit.

> [!TIP]
>
> Damit die Integration anomale PV-Erzeugungsraten erkennen kann, müssen die Erzeugungseinheiten regelmäßig an Home Assistant berichten. Unterstützt werden Einheiten, die periodisch einen aktuellen Erzeugungswert melden oder diesen in regelmäßigen Schritten erhöhen. Weist Ihre PV-Erzeugungseinheit kein solches Erzeugungsmuster auf, funktioniert die automatische Dämpfung möglicherweise nicht.

> [!NOTE]
>
> Die Erzeugungseinheiten für „entfernte“ Dachstandorte, die explizit von den Sensorgesamtwerten ausgeschlossen wurden, dürfen nicht berücksichtigt werden. Die automatische Dämpfung funktioniert für ausgeschlossene Dächer nicht.

##### Optionale Eingabe: Export der Website in das Raster, kombiniert mit einem Grenzwert

Wird überschüssiger, lokal erzeugter Strom in das Stromnetz eingespeist, ist die Exportmenge in der Regel begrenzt. Die Integration überwacht diesen Export. Werden Phasen der Exportbegrenzung erkannt (weil der Export fünf Minuten oder länger den Grenzwert erreicht), wird der entsprechende Erzeugungszeitraum standardmäßig für *alle* Tage, die von der automatischen Dämpfung berücksichtigt werden, ausgeschlossen. Dieser Mechanismus gewährleistet die Unterscheidung zwischen durch Verschattung (z. B. durch Bäume oder Schornsteine) oder durch künstliche Standortbedingungen bedingten Produktionsbegrenzungen.

Die Einspeisung ins Stromnetz erfolgt in der Regel mittags, einer Zeit, die selten von Verschattung betroffen ist.

Ein einzelner, ansteigender Energiesensor ist zulässig, der sich um Mitternacht auf Null zurücksetzt. Die optionale Exportgrenze kann nur in kW angegeben werden. Informationen zur Anpassung dieses Verhaltens („Ausschluss an allen Tagen“) finden Sie im Abschnitt „Erweiterte Optionen“.

> [!TIP]
>
> Der Exportgrenzwert wird von einigen PV-Systemkomponenten möglicherweise nicht exakt als der tatsächliche Grenzwert gemessen. Dies kann verwirrend sein, liegt aber an Abweichungen in den Stromzangen-Messkreisen.
>
> Beispiel: Bei einer Exportbegrenzung von 5,0 kW misst ein Enphase-Gateway möglicherweise exakt 5,0 kW, während ein Tesla-Batteriegateway in derselben Installation 5,3 kW misst. Wenn der für die automatische Dämpfung verwendete Sensorwert in diesem Fall vom Tesla-Gateway stammt, muss sichergestellt werden, dass die Exportbegrenzung auf 5,3 kW festgelegt ist.

##### Erste Aktivierung

Für die automatische Dämpfung ist ein Mindestdatensatz erforderlich. Die Erzeugungshistorie wird sofort aus dem Sensorverlauf (bzw. den Sensordaten) geladen, die geschätzten Ist-Werte von Solcast werden jedoch erst nach Mitternacht Ortszeit empfangen. Daher werden nach der ersten Aktivierung der Funktion höchstwahrscheinlich nicht sofort Dämpfungsfaktoren modelliert.

(Wenn es sich um eine Neuinstallation handelt, bei der die geschätzten Ist-Werte einmalig ermittelt werden, können die Faktoren sofort modelliert werden.)

> [!TIP]
>
> Die meisten Meldungen zur automatischen Dämpfung werden auf `DEBUG` Ebene protokolliert. Meldungen, die darauf hinweisen, dass Dämpfungsfaktoren noch nicht modelliert werden können (und den Grund dafür angeben), werden hingegen auf `INFO` Ebene protokolliert. Wenn Ihre minimale Protokollierungsstufe für die Integration `WARNING` oder höher ist, werden diese Benachrichtigungen nicht angezeigt.

##### Modifizierung des automatisierten Dämpfungsverhaltens

Die automatische Dämpfung ist für viele Anwender geeignet, es gibt jedoch Situationen, in denen sie in der vorliegenden Form nicht optimal ist. Für solche Fälle kann eine Anpassung des Verhaltens für fortgeschrittene Anwender wünschenswert sein.

Kern der automatischen Dämpfung ist, dass der PV-Erzeugungswert im Vergleich zur geschätzten tatsächlichen Erzeugung zuverlässig sein muss. Ist dieser Wert aufgrund künstlicher Abregelung (Begrenzung) unzuverlässig, muss die automatische Dämpfung dies erkennen. Bei einfacher Begrenzung der Netzeinspeisung auf einen festen Wert ist dies unkompliziert und eine integrierte Funktion. Es ist aber auch möglich, die Unzuverlässigkeit der PV-Erzeugung in einem bestimmten Zeitraum anhand komplexerer Umstände zu kennzeichnen.

Hier können Sie kreativ werden und einen speziell benannten, vorlagenbasierten Sensor verwenden, um PV-Generierungsintervalle zu ignorieren, wenn auf deren Genauigkeit nicht vertraut werden kann (d. h. nicht bei "voller" Produktion).

Beispiele hierfür sind, wenn keine Stromeinspeisung ins Netz möglich ist oder wenn man sich gegen die Einspeisung entscheidet. In diesen Fällen entspricht der Haushaltsverbrauch der Stromerzeugung, was die automatische Dämpfung beeinträchtigt.

Um das Verhalten der automatischen Dämpfung zu ändern, kann eine Vorlagenentität mit dem Namen `solcast_suppress_auto_dampening` erstellt werden. Dies kann entweder über die Plattform „sensor“, „binary_sensor“ oder „switch“ erfolgen.

Die Integration überwacht diese Entität auf Zustandsänderungen. Wenn der Zustand *innerhalb eines halbstündlichen PV-Erzeugungsintervalls zu irgendeinem Zeitpunkt* „ein“, „1“, „wahr“ oder „Wahr“ ist, signalisiert dies der automatischen Dämpfung, ihr Verhalten anzupassen und dieses Intervall auszuschließen. Ist der Zustand der Entität hingegen während des *gesamten Intervalls* „aus“, „0“, „falsch“ oder „Falsch“, wird das Intervall wie gewohnt in die automatische Dämpfung einbezogen.

Die Unterdrückung ergänzt zudem die durch die Erkennung von Exportbeschränkungen des Standorts bereitgestellte Funktion, sodass diese Konfigurationsaspekte wahrscheinlich entfernt oder sorgfältig geprüft werden sollten.

Es muss außerdem eine Historie der Zustandsänderungen enthalten, um sinnvoll zu sein, daher wird der Einstieg etwas Zeit in Anspruch nehmen. Hierbei sind gesunder Menschenverstand und Geduld gefragt.

> [!TIP]
>
> Setzen Sie gegebenenfalls auch die erweiterte Option `automated_dampening_no_limiting_consistency` auf `true` .
>
> Standardmäßig wird ein Intervall, für das an einem beliebigen Tag eine Begrenzung festgestellt wird, für alle Tage der letzten vierzehn Tage ignoriert, es sei denn, diese Option ist aktiviert.

Hier ist eine wahrscheinliche Implementierungssequenz:

1. Erstellen Sie die Vorlagenentität `solcast_suppress_auto_dampening` .
2. Schalten Sie die automatische Dämpfung aus, da sie sonst fehlerhaft und verwirrend ist (aber sie war bereits vorher fehlerhaft und verwirrend, da Sie aufgrund eines negativen Großhandelspreises nicht exportieren können oder dies nicht tun möchten).
3. Löschen Sie Ihre Datei `/config/solcast_solar/solcast-generation.json` . Jeglicher Verlauf könnte die Ergebnisse der automatisierten Dämpfung verfälschen.
4. Stellen Sie sicher, dass der Rekorder mit einem Wert von mindestens sieben für ` `purge_keep_days` konfiguriert ist. Bei aktivierter automatischer Dämpfung versucht er, bis zu sieben Tage an Erzeugungshistorie zu laden (eine erweiterte Option ermöglicht die Speicherung weiterer Tage). Lassen Sie ihn dies tun, wenn es soweit ist. Wenn Sie üblicherweise häufiger löschen, können Sie den Wert nach einer Woche wieder ändern. (Die Erfassung von geschätzten Istwerten muss nicht deaktiviert werden.)
5. Setzen Sie die erweiterte Option `automated_dampening_no_limiting_consistency` bei Bedarf auf `true`
6. Starten Sie HA komplett neu, um die Recorder-Einstellung zu aktivieren und der Solcast-Integration mitzuteilen, dass nun Generierungsdaten fehlen.
7. Warten Sie geduldig eine Woche ab, um eine Geschichte für das neue Unternehmen aufzubauen.
8. Aktivieren Sie die automatische Dämpfung und beobachten Sie, wie sie mit Ihrer Anpassungseinheit zusammenarbeitet.

Die Aktivierung der Protokollierung auf `DEBUG` -Ebene für die Integration macht sichtbar, was passiert, und ist daher während der Einrichtung sinnvoll. Sollten Sie Unterstützung benötigen, ist es *unerlässlich* , die Protokolle griffbereit zu haben und sie mit uns zu teilen.

##### Automatische Dämpfungsnoten

Ein modellierter Faktor von über 0,95 wird als nicht signifikant betrachtet und ignoriert. Wir freuen uns über Rückmeldungen dazu, ob diese kleinen Faktoren signifikant sein und berücksichtigt werden sollten.

Diese geringfügigen Faktoren würden anhand der prognostizierten Stromerzeugung korrigiert, sodass man argumentieren könnte, sie nicht zu ignorieren. Eine kleine und regelmäßige Abweichung von der Prognose ist jedoch wahrscheinlich eher auf eine fehlerhafte Konfiguration der Dachflächen oder saisonale Schwankungen als auf Verschattung zurückzuführen.

Ziel der automatisierten Dämpfung ist es nicht, Fehlkonfigurationen von Solcast-Dachanlagen oder Besonderheiten der Modultypen bei der Stromerzeugung zu korrigieren oder die Prognosegenauigkeit zu verbessern. Vielmehr geht es darum, aufgrund lokaler Faktoren konstant niedrigere Ist- als Sollwerte bei der Stromerzeugung zu erkennen.

> [!TIP]
>
> Wenn Sie historische Daten aus zwei Wochen gesammelt haben und Dämpfungsfaktoren für jede halbe Stunde bei Sonnenschein generiert werden, liegt mit hoher Wahrscheinlichkeit ein Konfigurationsproblem vor. Die tatsächliche Stromerzeugung entspricht nie der geschätzten, und Ihre Solcast-Dachanlage ist wahrscheinlich falsch konfiguriert.

Fehlkonfigurationen von Dachanlagen können die Prognoseergebnisse erheblich beeinflussen und sollten daher in den Dachanlageneinstellungen korrigiert werden. Es wird dringend empfohlen, die Korrektheit der Konfiguration und die hinreichende Genauigkeit der Prognosen an Tagen mit guter Stromerzeugung zu überprüfen, bevor die automatische Dämpfung konfiguriert wird. Anders ausgedrückt: Bei fragwürdigen Prognosen sollte die automatische Dämpfung deaktiviert werden, bevor die Ursache der fragwürdigen Prognosen analysiert wird.

Die durch die automatische Dämpfung vorgenommenen Anpassungen können die Bemühungen zur Behebung grundlegender Fehlkonfigurationsprobleme behindern, und wenn diese Funktion aktiviert ist, wird die Meldung eines Problems, bei dem eine Abweichung von der Vorhersage vorliegt und die automatische Dämpfung nicht beteiligt ist, die Problemlösung wahrscheinlich erschweren.

Das will keiner von uns.

Externe Energiesensoren (wie PV-Export und Standortexport) müssen eine Maßeinheit (mWh, Wh, kWh oder MWh) aufweisen und sich im Laufe eines Tages kumulativ erhöhen. Kann keine Maßeinheit ermittelt werden, wird kWh angenommen. Andere Einheiten wie GWh oder TWh sind im privaten Bereich nicht sinnvoll und würden bei der Umrechnung in kWh zu einem inakzeptablen Genauigkeitsverlust führen. Daher werden sie nicht unterstützt. Auch andere Energieeinheiten wie Joule und Kalorien werden nicht unterstützt, da sie für Elektrizität unüblich sind.

##### Rückmeldung

Wir freuen uns über Ihr Feedback zu Ihren Erfahrungen mit der automatischen Dämpfungsfunktion in den Diskussionen des Integrations-Repositorys.

Eine umfassende Protokollierung auf `DEBUG` -Ebene erfolgt, wenn die automatische Dämpfung aktiviert ist. Wir empfehlen Ihnen, die protokollierten Details zu prüfen und in jede Diskussion einzubeziehen, die auf einen Mangel, eine Erfahrung (sowohl positive als auch negative!) oder eine Verbesserungsmöglichkeit hinweisen könnte.

#### Einfache stündliche Dämpfung

Sie können den Dämpfungsfaktor für jede Stunde anpassen. Werte zwischen 0,0 und 1,0 sind zulässig. Ein Wert von 0,95 dämpft (reduziert) jeden Solcast-Vorhersagewert um 5 %. Dies wird in den Sensorwerten und -attributen sowie im Home Assistant-Energie-Dashboard angezeigt.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png" width="500">

> [!TIP]
>
> Die meisten Nutzer der Dämpfungskonfiguration geben keine Werte direkt in den Konfigurationseinstellungen ein. Stattdessen erstellen sie Automatisierungen, um Werte festzulegen, die für ihren Standort an verschiedenen Tagen oder in verschiedenen Jahreszeiten geeignet sind. Diese Automatisierungen rufen dann die Aktion `solcast_solar.set_dampening` auf.
>
> Faktoren, die eine Dämpfung erforderlich machen könnten, sind beispielsweise unterschiedliche Beschattunggrade zu Beginn oder am Ende des Tages in verschiedenen Jahreszeiten oder wenn die Sonne nahe am Horizont steht und dadurch lange Schatten von nahegelegenen Gebäuden oder Bäumen entstehen können.

#### Granulare Dämpfung

Die Dämpfung kann für einzelne Solcast-Standorte oder in Halbstundenintervallen eingestellt werden. Dazu ist entweder die Aktion `solcast_solar.set_dampening` oder das Erstellen/Ändern einer Datei namens `solcast-dampening.json` im Home Assistant-Konfigurationsordner erforderlich.

Die Aktion akzeptiert eine Zeichenkette mit Dämpfungsfaktoren sowie optional eine Standortressourcen-ID. (Der optionale Standort kann mit Bindestrichen oder Unterstrichen angegeben werden.) Für stündliche Dämpfung geben Sie 24 Werte an, für halbstündliche 48. Beim Aufruf der Aktion wird die Datei `solcast-dampening.json` erstellt oder aktualisiert, sobald ein Standort oder 48 Faktorwerte angegeben werden. Wenn die Gesamtdämpfung mit 48 Faktoren festgelegt wird, kann optional ein Standort „all“ angegeben (oder in diesem Fall einfach weggelassen) werden.

```yaml
action: solcast_solar.set_dampening
data:
  damp_factor: 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
  #site: 1234-5678-9012-3456
```

Wird keine Standortressourcen-ID angegeben und werden 24 Dämpfungswerte angegeben, wird die granulare Dämpfung entfernt, und die konfigurierte stündliche Gesamtdämpfung gilt für alle Standorte. (Die granulare Dämpfung kann auch über den Dialog `CONFIGURE` der Integration deaktiviert werden.)

Die Aktion muss nicht explizit aufgerufen werden. Stattdessen kann die Datei direkt aktualisiert werden und wird, falls erstellt oder geändert, automatisch gelesen und verwendet. Erstellungs-, Aktualisierungs- und Löschvorgänge dieser Datei werden überwacht, und die daraus resultierenden Änderungen an der gedämpften Vorhersage werden innerhalb von weniger als einer Sekunde nach dem Vorgang sichtbar.

Wenn die granulare Dämpfung für einen einzelnen Standort in einer Mehrstandortumgebung konfiguriert ist, gilt diese Dämpfung nur für die Vorhersagen dieses Standorts. Andere Standorte werden nicht gedämpft.

Die Dämpfung kann selbstverständlich für alle einzelnen Standorte festgelegt werden. In diesem Fall müssen alle Standorte die gleiche Anzahl an Dämpfungswerten angeben, entweder 24 oder 48.

<details><summary><i>Klicken Sie hier, um Beispiele für Dämpfungsdateien anzuzeigen.</i></summary>
</details>

Die folgenden Beispiele dienen als Vorlage für das Format der dateibasierten, granularen Dämpfung. Verwenden Sie unbedingt Ihre eigenen Website-Ressourcen-IDs anstelle der Beispiel-IDs. Die Datei sollte im Home Assistant-Konfigurationsordner unter dem Namen `solcast-dampening.json` gespeichert werden.

Beispiel für die stündliche Dämpfung an zwei Standorten:

```yaml
{
  "1111-aaaa-bbbb-2222": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "cccc-4444-5555-dddd": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Beispiel für die stündliche Dämpfung an einem einzelnen Standort:

```yaml
{
  "eeee-6666-7777-ffff": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Beispiel für eine halbstündliche Dämpfung an zwei Standorten:

```yaml
{
  "8888-gggg-hhhh-9999": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "0000-iiii-jjjj-1111": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Beispiel für eine halbstündliche Dämpfung für alle Standorte:

```yaml
{
  "all": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```




#### Lesen von Prognosewerten in einer Automatisierung

Die Aktion `solcast_solar.query_forecast_data` kann sowohl gedämpfte als auch ungedämpfte Vorhersagen zurückgeben (`include `undampened: true` ). Der Standort kann ebenfalls in den Aktionsparametern angegeben werden, falls eine detailliertere Aufschlüsselung gewünscht ist. (Der optionale Standort kann mit Bindestrichen oder Unterstrichen angegeben werden.)

```yaml
action: solcast_solar.query_forecast_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
  undampened: true
  #site: 1111-aaaa-bbbb-2222
```

Die ungedämpfte Vorhersagehistorie wird nur für 14 Tage gespeichert.

#### Ablesen von geschätzten Istwerten in einer Automatisierung

Bei der Berechnung der Dämpfung mittels einer Automatisierung kann es von Vorteil sein, geschätzte tatsächliche Vergangenheitswerte als Eingabe zu verwenden.

Dies ist mithilfe der Aktion `solcast_solar.query_estimate_data` möglich. Der Standort ist möglicherweise derzeit nicht in den Aktionsparametern enthalten. (Falls eine detaillierte Standortaufschlüsselung gewünscht ist, erstellen Sie bitte ein Ticket oder ein Diskussionsthema.)

```yaml
action: solcast_solar.query_estimate_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
```

Die geschätzten Ist-Daten werden 730 Tage lang gespeichert.

#### Ablesen der Dämpfungswerte

Die aktuell eingestellten Dämpfungsfaktoren können mit der Aktion „Solcast PV-Vorhersage: Dämpfung der Vorhersagen abrufen“ ( `solcast_solar.get_dampening` ) abgerufen werden. Dabei kann optional eine Standortressourcen-ID angegeben werden, alternativ kann kein Standort oder der Standort „alle“ angegeben werden. Wird kein Standort angegeben, werden alle Standorte mit eingestellter Dämpfung zurückgegeben. Ist für einen Standort keine Dämpfung eingestellt, wird ein Fehler ausgelöst.

Die optionale Adresse kann entweder mit Bindestrichen oder Unterstrichen angegeben werden. Verwendet der Dienstaufruf Unterstriche, so verwendet auch die Antwort Unterstriche.

Wenn die granulare Dämpfung so eingestellt ist, dass sowohl individuelle als auch standortübergreifende Dämpfungsfaktoren angegeben werden, führt der Versuch, individuelle Dämpfungsfaktoren abzurufen, dazu, dass die standortübergreifenden Dämpfungsfaktoren zurückgegeben werden, wobei der Standort als „alle“ angegeben wird. Dies liegt daran, dass die standortübergreifenden Dämpfungsfaktoren in diesem Fall die individuellen Standorteinstellungen überschreiben.

Beispielaufruf:

```yaml
action: solcast_solar.get_dampening
data:
  site: b68d-c05a-c2b3-2cf9
```

Beispielantwort:

```yaml
data:
  - site: b68d-c05a-c2b3-2cf9
    damp_factor: >-
      1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0
```

### Konfiguration der Sensorattribute

Es gibt eine ganze Reihe von Sensorattributen, die als Datenquelle für Vorlagensensoren, Diagramme usw. verwendet werden können, darunter eine Aufschlüsselung pro Standort, Schätzwerte für 10/50/90 Tage sowie eine detaillierte Aufschlüsselung pro Stunde und halbe Stunde für jeden Vorhersagetag.

Viele Benutzer werden diese Attribute nicht nutzen, daher können sie deaktiviert werden, wenn sie nicht benötigt werden, um die Unübersichtlichkeit (insbesondere in der Benutzeroberfläche und auch bei der Speicherung von Datenbankstatistiken) zu reduzieren.

Standardmäßig sind alle Funktionen aktiviert, außer „Detaillierte Vorhersage pro Standort“ und „Detaillierte Stundenprognose“. (Alle stündlichen und halbstündlichen Detailattribute werden nicht an den Home Assistant-Recorder gesendet, da diese Attribute sehr groß sind, zu einem übermäßigen Datenbankwachstum führen würden und langfristig wenig Nutzen haben.)

> [!NOTE]
>
> Wenn Sie das untenstehende Beispiel-PV-Diagramm implementieren möchten, müssen Sie die Aufschlüsselung der Details im Halbstundentakt sowie `estimate10` aktiviert lassen.

### Konfiguration der harten Grenze

Es besteht die Möglichkeit, eine „harte Grenze“ für die prognostizierte Wechselrichterleistung festzulegen. Diese Grenze begrenzt die Solcast-Prognosen auf einen Maximalwert.

Der Grenzwert kann als „Gesamtwert“ (gültig für alle Websites in allen konfigurierten Solcast-Konten) oder pro Solcast-Konto mit einem separaten Grenzwert für jeden API-Schlüssel festgelegt werden. (Im letzteren Fall trennen Sie die gewünschten Grenzwerte durch Kommas.)

Das Szenario, in dem diese Beschränkung angewendet werden muss, ist einfach, aber beachten Sie, dass dies bei den wenigsten PV-Anlagen der Fall sein wird. (Und wenn Sie Mikro-Wechselrichter oder einen Wechselrichter pro String verwenden, dann definitiv nicht. Dasselbe gilt für alle Module mit identischer Ausrichtung an einem einzigen Solcast-Standort.)

Stellen Sie sich vor, Sie haben einen einzelnen 6-kW-String-Wechselrichter und zwei angeschlossene Strings mit jeweils 5,5 kW potenzieller Leistung, die in entgegengesetzte Richtungen zeigen. Aus Sicht des Wechselrichters ist dies überdimensioniert. Es ist nicht möglich, in Solcast ein AC-Erzeugungslimit festzulegen, das diesem Szenario mit zwei Standorten gerecht wird. Beispielsweise kann ein String im Sommer am Vormittag oder Nachmittag 5,5 kW DC erzeugen, woraus 5 kW AC resultieren, und der andere String erzeugt wahrscheinlich ebenfalls Strom. Daher ist es nicht sinnvoll, in Solcast für jeden String ein AC-Limit von 3 kW (die Hälfte des Wechselrichters) festzulegen. Auch eine Festlegung auf 6 kW pro String ist nicht sinnvoll, da Solcast die potenzielle Erzeugung mit hoher Wahrscheinlichkeit überschätzen würde.

Der Grenzwert kann in der Integrationskonfiguration oder über die Serviceaktion `solcast_solar.set_hard_limit` in `Developer Tools` festgelegt werden. Um den Grenzwert zu deaktivieren, geben Sie im Konfigurationsdialog den Wert Null oder 100 ein. Zum Deaktivieren über einen Serviceaktionsaufruf verwenden Sie `solcast_solar.remove_hard_limit` . (Bei der Festlegung des Grenzwerts kann nicht der Wert Null angegeben werden.)

### Konfiguration ausgeschlossener Websites

Es ist möglich, einen oder mehrere Solcast-Standorte von der Berechnung der Sensorgesamtwerte und der Energie-Dashboard-Prognose auszuschließen.

Der Anwendungsfall besteht darin, dass ein oder mehrere lokale „Hauptstandorte“ die kombinierten Gesamtprognosewerte liefern und ein „Remote“-Standort separat mit Apex-Diagrammen und/oder Vorlagensensoren visualisiert wird, deren Werte aus den Attributen der Standortaufschlüsselungssensoren stammen. Es ist nicht möglich, einen separaten Energy-Dashboard-Feed aus Vorlagensensoren zu erstellen (diese Daten stammen direkt aus der Integration als Datenwörterbuch).

Die Verwendung dieser erweiterten Funktion zusammen mit Vorlagensensoren und Apex-Diagrammen ist nicht ganz einfach. Im Readme finden Sie jedoch Beispiele sowohl für Vorlagensensoren, die aus Attributdaten erstellt wurden, als auch für ein Apex-Diagramm. Siehe [„Interaktion“](#interacting) , [„Beispielvorlagensensoren“](#sample-template-sensors) und [„Beispiel-Apex-Diagramm für Dashboards“](#sample-apex-chart-for-dashboard) .

Die Konfiguration erfolgt über den Dialog `CONFIGURE` .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png" width="500">

Die Auswahl der auszuschließenden Standorte und das Klicken auf `SUBMIT` werden sofort wirksam. Es ist nicht erforderlich, auf eine Aktualisierung der Wettervorhersage zu warten.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png" width="500">

> [!NOTE]
>
> Die Websitenamen und Ressourcen-IDs stammen von den Websites, die zum Zeitpunkt des letzten Abrufs von Solcast (beim Start) bekannt waren. Es ist nicht möglich, gleichzeitig einen neuen API-Schlüssel hinzuzufügen und eine Website vom neuen Konto auszuschließen. Das neue Konto muss zuerst hinzugefügt werden. Dadurch wird die Integration neu gestartet und die neuen Websites geladen. Anschließend können die vom neuen Konto auszuschließenden Websites ausgewählt werden.

### Erweiterte Konfigurationsoptionen

Es ist möglich, das Verhalten einiger Integrationsfunktionen zu ändern, insbesondere bei der integrierten automatischen Dämpfung.

Diese Optionen können durch Erstellen einer Datei namens `solcast-advanced.json` im Home Assistant Solcast Solar-Konfigurationsverzeichnis (normalerweise `/config/solcast_solar` ) festgelegt werden.

Die verfügbaren Optionen sind in der Dokumentation unter [Erweiterte Optionen](https://github.com/BJReplay/ha-solcast-solar/blob/main/ADVOPTIONS.md) aufgeführt.

## Beispielvorlagensensoren

### Zusammenführung von Standortdaten

Ein möglicher Wunsch ist es, die Prognosedaten für mehrere Standorte, die zu einem Solcast-Konto gehören, zu kombinieren, um die detaillierten Daten des jeweiligen Kontos in einem Apex-Diagramm visualisieren zu können.

Dieser Code ist ein Beispiel dafür, wie man dies mithilfe eines Template-Sensors umsetzt, der alle PV50-Prognoseintervalle summiert, um eine tägliche Kontosumme zu erhalten, und zusätzlich ein Attribut „detaillierte Prognose“ aus allen kombinierten Intervalldaten erstellt, das in einer Visualisierung verwendet werden kann.

Die Standortaufschlüsselung muss in den Integrationsoptionen aktiviert sein (die detaillierte Prognoseaufschlüsselung ist nicht standardmäßig aktiviert).

**Code enthüllen**

<details><summary><i>klicken Sie hier</i></summary>
</details>

```yaml
template:
  - sensor:
      - name: "Solcast Combined API 1"
        unique_id: "solcast_combined_api_1"
        state: >
          {% set sensor1 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'b68d_c05a_c2b3_2cf9') %}
          {% set sensor2 = state_attr('sensor.solcast_pv_forecast_forecast_today', '83d5_ab72_2a9a_2397') %}
          {{ sensor1 + sensor2 }}
        unit_of_measurement: "kWh"
        attributes:
          detailedForecast: >
            {% set sensor1 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'detailedForecast_b68d_c05a_c2b3_2cf9') %}
            {% set sensor2 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'detailedForecast_83d5_ab72_2a9a_2397') %}
            {% set ns = namespace(i=0, combined=[]) %}
            {% for interval in sensor1 %}
              {% set ns.combined = ns.combined + [
                {
                  'period_start': interval['period_start'].isoformat(),
                  'pv_estimate': (interval['pv_estimate'] + sensor2[ns.i]['pv_estimate']),
                  'pv_estimate10': (interval['pv_estimate10'] + sensor2[ns.i]['pv_estimate10']),
                  'pv_estimate90': (interval['pv_estimate90'] + sensor2[ns.i]['pv_estimate90']),
                }
              ] %}
              {% set ns.i = ns.i + 1 %}
            {% endfor %}
            {{ ns.combined | to_json() }}
```




## Beispiel eines Apex-Diagramms für ein Dashboard

Der folgende YAML-Code erzeugt ein Diagramm der heutigen PV-Erzeugung, der PV-Prognose und der PV10-Prognose. [Apex Charts](https://github.com/RomRider/apexcharts-card) muss installiert sein.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png">

Passen Sie die Konfiguration mit den passenden Home Assistant-Sensoren an die heutige Gesamtsolarstromerzeugung und die PV-Leistung der Solarmodule an.

> [!NOTE]
>
> Die Tabelle geht davon aus, dass Solar-PV-Sensoren in kW angegeben sind. Sollten einige Sensoren jedoch in W angegeben sein, fügen Sie unter der Entitäts-ID die `transform: "return x / 1000;"` hinzu, um den Sensorwert in kW umzurechnen.

**Code enthüllen**

<details><summary><i>klicken Sie hier</i></summary>
</details>

```yaml
type: custom:apexcharts-card
header:
  title: Solar forecast
  show: true
  show_states: true
  colorize_states: true
apex_config:
  chart:
    height: 300px
  tooltip:
    enabled: true
    shared: true
    followCursor: true
graph_span: 24h
span:
  start: day
yaxis:
  - id: capacity
    show: true
    opposite: true
    decimals: 0
    max: 100
    min: 0
    apex_config:
      tickAmount: 10
  - id: kWh
    show: true
    min: 0
    apex_config:
      tickAmount: 10
  - id: header_only
    show: false
series:
  - entity: sensor.SOLAR_POWER
    name: Solar Power (now)
    type: line
    stroke_width: 2
    float_precision: 2
    color: Orange
    yaxis_id: kWh
    unit: kW
    extend_to: now
    show:
      legend_value: true
      in_header: false
    group_by:
      func: avg
      duration: 5m
  - entity: sensor.solcast_pv_forecast_forecast_today
    name: Forecast
    color: Grey
    opacity: 0.3
    stroke_width: 0
    type: area
    time_delta: +15min
    extend_to: false
    yaxis_id: kWh
    show:
      legend_value: false
      in_header: false
    data_generator: |
      return entity.attributes.detailedForecast.map((entry) => {
            return [new Date(entry.period_start), entry.pv_estimate];
          });
  - entity: sensor.solcast_pv_forecast_forecast_today
    name: Forecast 10%
    color: Grey
    opacity: 0.3
    stroke_width: 0
    type: area
    time_delta: +15min
    extend_to: false
    yaxis_id: kWh
    show:
      legend_value: false
      in_header: false
    data_generator: |
      return entity.attributes.detailedForecast.map((entry) => {
            return [new Date(entry.period_start), entry.pv_estimate10];
          });
  - entity: sensor.SOLAR_GENERATION_ENERGY_TODAY
    yaxis_id: header_only
    name: Today Actual
    stroke_width: 2
    color: Orange
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_today
    yaxis_id: header_only
    name: Today Forecast
    color: Grey
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_today
    attribute: estimate10
    yaxis_id: header_only
    name: Today Forecast 10%
    color: Grey
    opacity: 0.3
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_remaining_today
    yaxis_id: header_only
    name: Remaining
    color: Grey
    show:
      legend_value: true
      in_header: true
      in_chart: false
```




## Bekannte Probleme

- Eine Änderung der Grenzwerte wird die aufgezeichneten Prognosedaten verändern. Dies ist derzeit so vorgesehen und wird sich voraussichtlich nicht ändern.
- Alle leeren JSON-Integrationsdateien werden beim Start entfernt (siehe unten).
- Beispielstandorte (sofern in Ihrem Solcast-Dashboard eingerichtet) werden in die von dieser Integration abgerufenen und an Home Assistant zurückgegebenen Prognosen einbezogen (siehe unten).

### Entfernung von Dateien der Länge Null

In der Vergangenheit kam es vereinzelt vor, dass die Cache-Dateien von der Integration als leere Dateien geschrieben wurden. Dies geschah jedoch äußerst selten und sollte Sie daran erinnern, regelmäßig Sicherungskopien Ihrer Installation anzulegen.

Die Ursache könnte ein Code-Problem sein (das wiederholt untersucht und wahrscheinlich in Version 4.4.8 behoben wurde) oder ein externer Faktor, den wir nicht kontrollieren können. Es tritt jedoch definitiv beim Herunterfahren auf, wobei die Integration (zuvor) nicht wieder startet. Dies geschieht in der Regel nach einem Upgrade.

Die Daten sind verloren. Die Lösung bestand darin, die leere Datei zu löschen oder die Datei aus der Sicherung wiederherzustellen und anschließend neu zu starten.

Ab Version 4.4.10 startet das System nun mit einer leeren Datei und protokolliert als `CRITICAL` Fall, dass die Datei entfernt wurde. Dies führt zu zusätzlichen API-Aufrufen beim Start. ***Ihre gesamte Prognosehistorie geht wahrscheinlich verloren.***

Es kann zu Problemen bei der API-Nutzung kommen, die jedoch innerhalb von 24 Stunden behoben sein werden.

### Probenentnahmestellen

Wenn Sie Beispielstandorte sehen (wie diese) [](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png"> ) Entfernen Sie sie aus Ihrem Solcast-Dashboard.

## Fehlerbehebung

<details><summary><i>Klicken Sie hier, um die Tipps zur Fehlerbehebung auszublenden.</i></summary>
</details>

Diese Integration ist darauf ausgelegt, bei einwandfreiem Betrieb nur sehr wenige Protokolleinträge zu erstellen. Bei Problemen werden `ERROR` oder `CRITICAL` Protokolleinträge erzeugt, bei vorübergehenden oder kleineren Problemen hingegen `WARNING` . Überprüfen Sie die Protokolle immer als ersten Schritt bei der Fehlerbehebung.

Um detailliertere Protokollierung zu ermöglichen, werden viele Einträge auf der Stufe `DEBUG` ausgegeben. Es wird empfohlen, die Debug-Protokollierung zur Fehlerbehebung zu aktivieren. Beachten Sie, dass ein Neustart von Home Assistant erforderlich ist, um die Protokollierungsstufe zu ändern. Dabei wird die aktuelle Datei `homeassistant.log` in `homeassistant.log.1` umbenannt (es gibt keine `.2` Datei, daher sind nur diese und die vorherige Sitzung zugänglich).

In `/homeassistant/configuration.yaml` :

```
logger:
  default: warn
  logs:
    custom_components.solcast_solar: debug
```

Das Überprüfen von Protokollen ist recht einfach, Debug-Protokolle können jedoch nicht über die Benutzeroberfläche eingesehen werden. Die Datei `/homeassistant/home-assistant.log` home-assistant.log` muss manuell angezeigt werden. Verwenden Sie dazu in einer SSH-Sitzung den Befehl `less /homeassistant/home-assistant.log` . Je nach installierten Add-ons stehen Ihnen möglicherweise weitere Möglichkeiten zum Anzeigen dieser Datei zur Verfügung.

### API-Schlüsselprobleme

Während der Konfiguration geben Sie einen oder mehrere API-Schlüssel ein. Die unter solcast.com konfigurierten Websites werden nun abgerufen, um den Schlüssel zu testen. Fehler lassen sich in der Regel auf wenige Kategorien einteilen: Der Schlüssel ist falsch, im Solcast-Konto sind keine Websites konfiguriert oder solcast.com ist nicht erreichbar. Diese Fälle sind meist selbsterklärend.

Falls solcast.com nicht erreichbar ist, sollten Sie die Ursache des Problems generell woanders suchen. Bei einem vorübergehenden Fehler, wie z. B. der Fehlermeldung `429/Try again later` , befolgen Sie bitte die Anweisung, zu warten und die Einrichtung dann erneut zu versuchen. (Die Solcast-Website ist in der Regel alle 15 Minuten, insbesondere zur vollen Stunde, stark überlastet.)

### Probleme mit der Wettervorhersage

Bei einer Wettervorhersageaktualisierung greift ein Wiederholungsmechanismus, um vorübergehende `429/Try again later` -Situationen zu bewältigen. Es kommt äußerst selten vor, dass alle zehn Versuche fehlschlagen; dies ist jedoch am frühen Morgen in Europa möglich. In diesem Fall wird die nächste Aktualisierung mit hoher Wahrscheinlichkeit erfolgreich sein.

Ein API-Nutzungszähler erfasst die Anzahl der täglichen Aufrufe an solcast.com (beginnend um Mitternacht UTC). Sollte dieser Zählerstand nicht der Realität entsprechen, wird er bei einer Ablehnung des API-Aufrufs auf seinen Maximalwert gesetzt und erst wieder um Mitternacht UTC zurückgesetzt.

### Die prognostizierten Werte sehen "einfach falsch" aus.

Möglicherweise sind auf solcast.com noch Demo-Websites konfiguriert. Überprüfen Sie dies und löschen Sie sie gegebenenfalls.

Überprüfen Sie bitte auch Ihre Azimut-, Neigungs-, Standort- und sonstigen Einstellungen für die Standorte. „Einfach falsche“ Werte werden nicht durch die Integration verursacht, sondern sind ein Anzeichen dafür, dass mit der Gesamtkonfiguration etwas nicht stimmt.

### Ausnahmen in den Protokollen

Ausnahmen sollten nur protokolliert werden, wenn ein schwerwiegender Fehler vorliegt. Werden sie protokolliert, sind sie meist ein Symptom der zugrundeliegenden Ursache, kein Codefehler und stehen in der Regel nicht in direktem Zusammenhang mit der eigentlichen Ursache des Problems. Suchen Sie nach möglichen Ursachen in Änderungen.

Wenn Ausnahmen auftreten, werden die Sensorzustände wahrscheinlich `Unavailable` , was ebenfalls ein Symptom für das Auftreten einer Ausnahme ist.

Wenn Sie von einer sehr alten oder völlig anderen Solcast-Integration „aktualisieren“, handelt es sich nicht um ein „Upgrade“, sondern um eine Migration. Betrachten Sie es daher auch so. Einige Migrationsszenarien werden beschrieben, andere erfordern jedoch möglicherweise die vollständige Entfernung aller inkompatiblen Daten, die schwerwiegende Probleme verursachen könnten. Informationen zum Speicherort einiger möglicherweise störender Dateien finden Sie unter [„Vollständige Entfernung der Integration“](#complete-integration-removal) .

Codefehler können zwar vorkommen, sollten aber nicht der erste Verdachtspunkt sein. Vor der Veröffentlichung wird der Code mit PyTest umfangreichen automatisierten Tests unterzogen, die ein breites Spektrum an Szenarien abdecken und jede einzelne Codezeile ausführen. Einige dieser Tests gehen von ungünstigsten Situationen aus, die Ausnahmen verursachen können, wie beispielsweise beschädigte Cache-Daten. In solchen Fällen sind Ausnahmen zu erwarten.

### Schlusswort

Sollten äußerst ungewöhnliche Verhaltensweisen auftreten, die mit dem Auftreten von Ausnahmen einhergehen, kann eine schnelle Lösung darin bestehen, alle `/homeassistant/solcast*.json` zu sichern, diese zu entfernen und anschließend die Integration neu zu starten.




## Vollständige Integrationsentfernung

Um alle Spuren der Integration vollständig zu entfernen, navigieren Sie zunächst zu `Settings` | `Devices & Services` | `Solcast PV Forecast` , klicken Sie auf die drei Punkte neben dem Zahnradsymbol ( `CONFIGURE` in früheren HA-Versionen) und wählen Sie `Delete` .

An diesem Punkt wurden die Konfigurationseinstellungen zurückgesetzt, aber der Code und die Prognoseinformationen bleiben im Cache gespeichert (bei einer erneuten Einrichtung der Integration werden diese zwischengespeicherten Daten wiederverwendet, was unter Umständen erwünscht ist oder auch nicht).

Die Cache-Dateien befinden sich im Konfigurationsordner von Home Assistant Solcast Solar (normalerweise `/config/solcast_solar` oder `/homeassistant/solcast_solar` , der genaue Speicherort kann jedoch je nach Home Assistant-Bereitstellungstyp variieren). Diese Dateien sind nach der Integration benannt und können mit `rm solcast*.json` entfernt werden.

Der Code selbst befindet sich unter `/config/custom_components/solcast_solar` . Durch das Entfernen dieses gesamten Ordners wird die Integration vollständig entfernt.

## Änderungen

Version 4.4.10

- Beheben Sie die Ausnahme „Fehlende Datensätze, reparierbares Problem“ durch @autoSteve
- Problem mit fehlender Vorhersagehistorie behoben (#423) von @autoSteve
- Entfernt leere Cache-Dateien beim Start von @autoSteve
- Erweiterte Option „granular_dampening_delta_adjustment“ von @autoSteve hinzugefügt
- Umbenennung von automated_dampening_no_delta_adjustment durch @autoSteve
- Warnung und Problem mit veralteten erweiterten Optionen von @autoSteve
- Das von @autoSteve gemeldete Problem betrifft Fehlersituationen bei erweiterten Optionen.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.9...v4.4.10

Version 4.4.9

- Erweiterte Optionen für automatische Dämpfungsmodellvarianten von @Nilogax hinzugefügt
- Erweiterte Option „Automatische Dämpfungs-Delta-Anpassungsvariante“ von @Nilogax hinzugefügt
- Erweiterte Option „Automatische Dämpfung beibehalten“ von @Nilogax hinzugefügt
- Erweiterte Option zur automatischen Dämpfungsunterdrückung hinzugefügt von @autoSteve
- Unterstützung für die Switch-Plattform zur Unterdrückung von Erzeugungseinheiten durch @autoSteve hinzugefügt
- Die Unterdrückung kann nun täglich in jedem Bundesstaat durch @autoSteve beginnen und enden.
- Startverhalten optimieren und Startstatusmeldungen übersetzen von @autoSteve
- Fehlerbehebung bei der Aktualisierung der Dämpfungsentität für die stündliche Dämpfung, die durch eine Aktion auf alle 1.0 gesetzt wird (von @autoSteve)
- Behebt einen harmlosen Fehler beim Startvorgang, wenn die geschätzten Istwerte noch nicht von @autoSteve erfasst wurden.
- Behebung einer Ausnahme bei Verwendung der stündlichen Dämpfung, wenn die Dämpfungsentität von @autoSteve aktiviert wurde.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.8...v4.4.9

Version 4.4.8

- Alle Cache- und Konfigurationsdateien nach `config/solcast_solar` verschieben (von @autoSteve)
- Die Solcast-API ist vorübergehend nicht verfügbar. Dieses Problem wurde von @autoSteve gemeldet.
- Verbesserung des Reparaturhinweises „Zukunftsprognosen fehlen bei aktivierter automatischer Aktualisierung“ von @gcoan
- Bitte schlagen Sie nach API-Fehlern von @autoSteve keine Hinweise auf „behebbare“ Reparaturen für manuelle Updates vor.
- Angepasste automatische Dämpfungsfaktoren oberhalb des Schwellenwerts „unbedeutend“ von @autoSteve ignorieren
- Erweiterte automatische Dämpfungsoption „Unbedeutender Faktor angepasst“ von @autoSteve hinzugefügt
- Erweiterte automatische Dämpfungsoption „ähnlicher Spitzenwert“ von @autoSteve hinzugefügt
- Erweiterte Option für automatische Dämpfung „Generationsabrufverzögerung“ von @autoSteve hinzugefügt
- Erweiterte Option für geschätzte Istwerte „Kartenaufschlüsselung protokollieren“ von @autoSteve hinzugefügt
- Erweiterte Option für geschätzte Istwerte „APE-Perzentile protokollieren“ von @autoSteve hinzugefügt
- Die Option „Abrufverzögerung“ für erweiterte Schätzwerte wurde von @autoSteve hinzugefügt.
- Erweiterte allgemeine Option „Benutzeragent“ hinzugefügt von @autoSteve
- Die Option „Minimale Anpassungsintervalle“ für die erweiterte automatische Dämpfung wurde von @autoSteve so geändert, dass sie `1` akzeptiert.
- Attributkonsistenz als lokale Zeitzone für Datums- und Zeitwerte von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.7...v4.4.8

Version 4.4.7

- Erweiterte Optionen-Konfigurationsdatei von @autoSteve hinzufügen
- Füge das Attribut `custom_hours` zum Sensor `Forecast Next X Hours` von @autoSteve hinzu
- Automatische Dämpfung, Verbesserung der Ausschließung unzuverlässiger Intervallgenerierung durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.6...v4.4.7

Version 4.4.6

- Behoben: Automatische Dämpfung, Ignorieren von Generationstagen mit einer geringen Anzahl historischer Stichproben von @autoSteve
- Behoben: Die automatische Dämpfungsmodellierung wurde auf 14 Tage beschränkt (vorher abhängig vom Generationsverlauf) von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.5...v4.4.6

Version 4.4.5

- Der Übergang zwischen Normal- und Winterzeit in Europa/Dublin wird von @autoSteve unterstützt.
- Automatische Dämpfung, Nutzung der Interquartils-Anomalieerkennung für Generierungsentitäten von @autoSteve
- Automatische Dämpfung, Anpassung an generationskonsistente oder zeitkonsistente Generierungselemente von @autoSteve
- Automatische Dämpfung, Ignorieren ganzer Generationsintervalle mit Anomalien von @autoSteve
- Automatische Dämpfung, Mindestanzahl übereinstimmender Intervalle muss größer als eins sein (von @autoSteve)
- Automatische Dämpfung, Unterstützung für die Unterdrückung von Erzeugungsentitäten hinzugefügt von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.4...v4.4.5

Version 4.4.4

- Behoben: Automatische Dämpfung, an die Tageslichtdauer angepasstes Intervall von @rcode6 und @autoSteve
- Ignorierte ungewöhnliche Azimutprobleme von @autoSteve entfernen und unterdrücken

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.3...v4.4.4

Version 4.4.3

- Zufällige Istwerte abrufen, dann sofortige automatische Dämpfungsmodellierung durch @autoSteve
- Entitäten mit deaktivierter automatischer Dämpfung von der Auswahl durch @autoSteve ausschließen
- Automatische Dämpfung, Ausschluss von exportbegrenzten Intervallen von allen Tagen von @autoSteve
- Automatische Dämpfung, Übergang zwischen Tageslicht und Licht wird von @autoSteve gesteuert
- Erhalten Sie bis zu vierzehn Tage Wettervorhersagedaten von @autoSteve
- Behoben: Aktualisierung der Dämpfungsfaktorentabelle in TEMPLATES.md durch @jaymunro
- Behoben: Tippfehler im Sensornamen in TEMPLATES.md von @gcoan korrigiert
- Mindestversion von Home Assistant: 2025.3

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.2...v4.4.3

Version 4.4.2

- Automatische Dämpfung, Anpassung an periodisch aktualisierte Generierungseinheiten (Envoy) von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.1...v4.4.2

Version 4.4.1

- Automatische Anpassung der Maßeinheit für Generierung/Export durch @brilthor und @autoSteve
- Ignoriere atypische Generationsentitätssprünge von @autoSteve
- Für die automatische Dämpfung durch @autoSteve ist eine Mehrheit der tatsächlichen „Guttag“-Daten erforderlich.
- @Nilogax hat ein Beispiel für ein Diagramm zur automatischen Dämpfung (angewandter Wert vs. Basiswert) in die Datei TEMPLATES.md eingefügt. Danke!
- Umfangreiche Aktualisierungen der README.md-Datei zur automatischen Dämpfung durch @autoSteve, @gcoan und @Nilogax. Vielen Dank!
- Behoben: Migration der Nutzung ohne Zurücksetzen, Schlüsseländerung ohne Änderung der Websites durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.0...v4.4.1

Version 4.4.0

- Automatische Dämpfungsfunktion hinzugefügt von @autoSteve
- Die modifizierten Dämpfungsfaktoren werden ab dem heutigen Tag von @autoSteve angewendet.
- Behebung des Problems, dass die maximale Attributgröße übersetzter Sensoren von @autoSteve überschritten wurde.
- Überwachen Sie die Datei solcast-dampening.json auf Erstellungs-/Aktualisierungs-/Löschvorgänge durch @autoSteve
- Füge das Attribut last_attempt zur Entität api_last_polled hinzu (von @autoSteve)
- Fügen Sie den Website-Parameter „allow action site“ mit Bindestrich oder Unterstrich von @autoSteve hinzu.
- Test für ungewöhnlichen Azimut hinzugefügt von @autoSteve
- Fix Energy Dashboard start/end points by @autoSteve
- Namensnennung nur dort, wo sie angebracht ist, von @autoSteve
- Mindestversion von HA: 2024.11

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.5...v4.4.0

### Vorherige Änderungen

<details><summary><i>Klicken Sie hier, um die Änderungen auf Version 3.0 zurückzusetzen.</i></summary>
</details>

Version 4.3.5

- Behebung des Problems mit der API-Schlüsseländerungserkennung auf Fehler 429 bei Verwendung mehrerer Schlüssel durch @autoSteve
- Behebt einen Sonderfall bei der Schlüsselvalidierung, der den Start durch @autoSteve verhindern könnte.
- Fügt dem zuletzt abgefragten Sensor Attribute zur Zählung von Aktualisierungsfehlern hinzu (von @autoSteve)
- Erlaube, dass bei einem 429-Fehler alle 30 Minuten eine Website abgerufen werden kann (von @autoSteve).
- Strengere Typüberprüfung von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.4...v4.3.5

Version 4.3.4

- Dachstandort-Tags in Standortsensorattribute einbinden von @autoSteve
- Entfernen Sie die störenden Start-Debug-Protokolle, die von @autoSteve auf kritischer Ebene protokolliert wurden.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.3...v4.3.4

Version 4.3.3

- Standorte hinzufügen, die von den Gesamtsummen und dem Energie-Dashboard ausgeschlossen werden sollen (von @autoSteve)
- Portugiesische Übersetzung hinzugefügt von @ViPeR5000 (vielen Dank!)
- Bereinigung verwaister Diagnosesensoren für harte Grenzwerte von @autoSteve
- Vermeiden Sie einen Initialisierungsabsturz durch wiederholtes Aufrufen von rooftop_sites durch HA-Neustarts von @autoSteve
- Korrektur der Diagnosesensorwerte für die Beschränkung mehrerer API-Schlüssel durch @autoSteve
- Behebung des Problems, dass verwaiste Cache-Daten entfernt wurden, wenn der API-Schlüssel nicht-alphanumerische Zeichen enthielt (von @autoSteve).
- Die Formatierung der granularen Dämpfung in solcast-dampening.json wurde von @autoSteve auf eine halb-eingerückte Darstellung korrigiert.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.2...v4.3.3

Version 4.3.2

- Ersetzen Sie den Bindestrich durch einen Unterstrich in den Namen der Website-Aufschlüsselungsattribute von @autoSteve
- Spanische Übersetzung hinzugefügt von @autoSteve
- Italienische Übersetzung hinzugefügt von @Ndrinta (vielen Dank!)

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.1...v4.3.2

Version 4.3.1

- HACS-Standardinstallationsanweisungen von @BJReplay hinzufügen

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.0...v4.3.1

Version 4.3.0

- Behebung eines Problems, wenn die halbstündliche Aufschlüsselung deaktiviert, die stündliche jedoch aktiviert ist (von @autoSteve)
- Behebung eines Problems beim Übergang von der granularen zur herkömmlichen Dämpfung durch @autoSteve
- Behebung eines Problems bei der Verwendung mehrerer harter Grenzwerte durch @autoSteve
- Behebung eines Problems mit veraltetem Startzustand bei aktivierter automatischer Aktualisierung durch @autoSteve
- Füge automatische Aktualisierungsattribute zu api_last_polled von @autoSteve hinzu
- Datendateien vom v3-Integrationsschema von @autoSteve aktualisieren
- Konfigurations- und Optionsabläufe prüfen gültige API-Schlüssel und verfügbare Websites (von @autoSteve)
- Füge erneute Authentifizierung und neu konfigurierte Abläufe von @autoSteve hinzu
- Füge Reparaturabläufe für Prognosen hinzu, die von @autoSteve nicht aktualisiert werden
- Geschätzte Istwerte bei veralteten Startwerten abrufen (von @autoSteve)
- Sensoren bei Integrationsfehler auf „nicht verfügbar“ setzen (von @autoSteve)
- Doppelte API-Schlüsselangaben von @autoSteve erkennen
- Überprüfung auf Integrationskonflikte von @autoSteve entfernt
- Integrations- und Unit-Tests von @autoSteve hinzufügen
- Strenge Typüberprüfung durch @autoSteve
- Füge von @autoSteve einen Abschnitt zur Fehlerbehebung in der README.md-Datei hinzu.
- Behebung eines Problems mit fehlerhaften Prognosen durch Hinweise zum Entfernen von Beispielstandorten aus dem Solcast-Dashboard (von @BJReplay)
- Aktualisierte Problemvorlage von @BJReplay

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.7...v4.3.0

Version 4.2.7

- Behebung eines Problems mit der API-Schlüsselvalidierung durch @autoSteve
- Behebt ein Problem, das die saubere Entfernung der Integration durch @autoSteve verhindert.
- Verbesserung der Prüfung auf Integrationskonflikte von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.6...v4.2.7

Version 4.2.6

- Behebung eines Problems, das Neuinstallationen verhinderte (von @autoSteve)
- Behebung eines Problems bei der Berechnung des automatischen Aktualisierungsintervalls für mehrere API-Schlüssel durch @autoSteve
- Behebung eines Problems bei der Migration von/zu Multi-API für Docker-Setups von @autoSteve
- Problem beim Löschen des gesamten Vorhersageverlaufs behoben von @autoSteve
- Behebung eines Problems, bei dem der API-Zähler bei veralteten Startabfragen nicht erhöht wurde (von @autoSteve).
- Behebt ein Problem, bei dem die von @autoSteve angegebenen API-Nutzungs-/Gesamt- und zuletzt aktualisierten Sensoren nicht aktualisiert wurden.
- Solcast-API-Simulator hinzugefügt, um die Entwicklung zu unterstützen und das Testen zu beschleunigen (von @autoSteve)

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.5...v4.2.6

Version 4.2.5

- Mehrere API-Schlüssel mit fester Begrenzung versehen von @autoSteve
- Proportionale Begrenzung von Website-Ausfällen durch @autoSteve
- Tägliche Website-Zahlen korrekt anhand des Limits berechnen (von @autoSteve)
- Sofortige Anwendung der Dämpfung auf zukünftige Prognosen durch @autoSteve
- Behebung von Problemen mit dem Übergang zur Sommerzeit durch @autoSteve
- Systemzustandsausgabefehler von @autoSteve behoben
- Verbesserungen der Protokollierung für ein besseres Situationsbewusstsein durch @autoSteve
- Automatische Aktualisierung toleriert Neustart unmittelbar vor dem geplanten Abruf durch @autoSteve
- Polnische Übersetzung aktualisiert, mit Dank an @erepeo

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.4...v4.2.5

Version 4.2.4

- Hinzufügen eines User-Agent-Headers zu API-Aufrufen von @autoSteve
- Siehe Aktion statt Serviceaufruf von @gcoan

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.3...v4.2.4

Version 4.2.3

- Behebt ein Problem, das das Ändern von Solcast-Konten verhindert (von @autoSteve)
- Behebt ein Problem mit mehreren API-Schlüsseln, bei dem die API-Nutzungsrücksetzung von @autoSteve nicht korrekt verarbeitet wurde.
- Behebung eines Problems mit aktivierter detaillierter Website-Aufschlüsselung für stündliche Attribute durch @autoSteve
- Codebereinigung und Refactoring durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.0...v4.2.3

Version 4.2.1 / Version 4.2.2

- Aufgrund eines Problems wurden Veröffentlichungen zurückgezogen.

Version 4.2.0

- Allgemein verfügbare Version 4.1.8 und Vorabversion 4.1.9 mit neuen Funktionen
- Übersetzungen von Fehlermeldungen des Serviceaufrufs von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.2.0

Die aktuellsten Änderungen: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.9...v4.2.0

Vorabversion v4.1.9

- Granulare Dämpfung zur Dämpfung pro halbstündigem Zeitraum von @autoSteve und @isorin
- Die Dämpfung wurde von @autoSteve und @isorin beim Abruf der Prognose und nicht in der Prognosehistorie angewendet.
- Abrufen ungedämpfter Prognosewerte mithilfe des Serviceaufrufs von @autoSteve (danke an @Nilogax)
- Die aktuell eingestellten Dämpfungsfaktoren können Sie über den Serviceanruf von @autoSteve abrufen (vielen Dank an @Nilogax).
- Migration der ungedämpften Prognose in den ungedämpften Cache beim Start durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.8...v4.1.9

Vorabversion v4.1.8

- Automatisierte Wettervorhersage-Aktualisierungen, die keine Automatisierung durch @autoSteve und @BJReplay erfordern
- Zusätzliche Dämpfung pro Standort von @autoSteve
- Füge die Option zur detaillierten Standortanalyse für Prognosen von @autoSteve hinzu
- Füge von @autoSteve eine Konfiguration für feste Limits zu den Optionen hinzu.
- Integrationsneuladen unterdrücken, wenn viele Konfigurationsoptionen von @autoSteve geändert werden

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.1.8

Version 4.1.7

- Behebung von Problemen mit der Website-Auflösung für Websites, die später von @autoSteve hinzugefügt wurden
- Behebung von Problemen mit der Website-Aufschlüsselung für Keilwellensensoren durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.6...v4.1.7

Version 4.1.6

- Vereinfachung des Konfigurationsdialogs durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.5...v4.1.6

Vorabversion v4.1.5

- Fehler: Der im Nutzungs-Cache gespeicherte Zeitstempel war falsch (von @autoSteve)
- Bug: Hinzufügen der Verwendung zum Zurücksetzen des API-Schlüssels für den ersten Schlüssel von @autoSteve
- Fehler: Fehlender Iterator bei der Überprüfung neuer Websites durch @autoSteve
- Umgehungslösung für einen möglichen HA-Planungsfehler von @autoSteve
- Code-Stilanpassung an HA-Stilrichtlinien von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.4...v4.1.5

Vorabversion v4.1.4

- Aktualisierte polnische Übersetzung von @home409ca
- Umbenennung der Integration in HACS in Solcast PV Forecast von @BJReplay
- Die Versionsanforderung für aiofiles wurde von @autoSteve auf &gt;=23.2.0 reduziert.
- Verbesserungen im Konfigurationsdialog von @autoSteve
- Diverse Übersetzungsaktualisierungen von @autoSteve
- Refactoring-Moment und verbleibender Spline-Build von @autoSteve
- Negative Vorhersagen für den X-Stunden-Sensor verhindern (von @autoSteve)
- Spline-Bounce für reduzierte Spline-Linien unterdrücken (von @autoSteve)
- Sorgfältigere Serialisierung von solcast.json durch @autoSteve
- Überwachen Sie den Zeitstempel der letzten Aktualisierung der sites-usage.json-Datei durch @autoSteve
- Umfangreiche Codebereinigung durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.3...v4.1.4

Version 4.1.3

- Die Entfernung des API-Aufrufs GetUserUsageAllowance durch @autoSteve wird berücksichtigt.
- Halbierung der Wiederholungsverzögerungen durch @autoSteve
- Readme-Verbesserungen von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.2...v4.1.3

Version 4.1.2

- Fünfzehnminütige Schicht, da 30-Minuten-Durchschnittswerte von @autoSteve vorliegen
- Erhöhung der Prognoseabrufversuche auf zehn durch @autoSteve
- Bilder in Screenshots umwandeln von @BJReplay
- Behebung des Problems, dass die Readme-Bilder im HACS-Frontend nicht angezeigt werden.

Ersetzt Version 4.1.1

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.0...v4.1.2

Version 4.1

- Erste größere Version seit v4.0.31, die nicht als Vorabversion gekennzeichnet wurde.
- Die vorherigen Versionen liefen größtenteils recht stabil, aber wir sind zuversichtlich, dass diese Version nun für alle bereit ist.
- Änderungen seit Version 4.0.31:
    - Deutlich verbesserte Stabilität für alle und ein optimiertes Starterlebnis für neue Benutzer
    - Zusätzliche Sensorattribute
    - Neue Konfigurationsoptionen zur Unterdrückung von Sensorattributen
    - Schwärzung sensibler Informationen in Debug-Protokollen
    - Verbesserte Effizienz durch viele Sensoren, deren Berechnungen in Fünf-Minuten-Intervallen erfolgen, einige nur beim Abrufen von Vorhersagen.
    - Spline-Interpolation für „momentane“ und „periodische“ Sensoren
    - Fehlerbehebungen für Benutzer mit mehreren API-Schlüsseln
    - Fehlerbehebungen für Docker-Nutzer
    - Verbesserungen bei der Ausnahmebehandlung
    - Verbesserungen bei der Protokollierung
- @autoSteve wird als CodeOwner willkommen geheißen.
- Es ist nun offensichtlich, dass dieses Repository wahrscheinlich erst nach der Veröffentlichung von HACS 2.0 als Standard-Repository in HACS hinzugefügt wird. Daher wird in der Installationsanleitung klargestellt, dass das Hinzufügen über den manuellen Repository-Workflow die bevorzugte Vorgehensweise ist, und es wurden neue Anweisungen hinzugefügt, die zeigen, wie dies funktioniert.

Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.1.0

Die aktuellsten Änderungen: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.43...v4.1.0

Version 4.0.43

- Automatisches Abrufen der Prognosedaten beim Start, wenn veraltete Daten von @autoSteve erkannt werden

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.42...v4.0.43

Version 4.0.42

- Meldung von Ladefehlern an den ersten Standorten und automatische HA-Wiederholungsversuche von @autoSteve
- Unterdrückung des Spline-Bounces in Moment-Splines durch @autoSteve
- Splines um Mitternacht neu berechnen, bevor die Sensoren aktualisiert werden (von @autoSteve)
- Readme-Aktualisierungen von @autoSteve
- Dämpfung und harte Grenzwerte wurden aus den standortspezifischen Prognoseaufschlüsselungen entfernt (zu streng, zu irreführend) von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.41...v4.0.42

Version 4.0.41

- Interpolierte Vorhersage 0/30/60 Korrektur #101 von @autoSteve
- Sicherstellen, dass das Konfigurationsverzeichnis immer relativ zum Installationsort ist #98 von @autoSteve
- Füge state_class zu `power_now_30m` und `power_now_1hr` hinzu, um sie `power_now` anzupassen (von @autoSteve; LTS wird entfernt, aber LTS ist für diese Sensoren nicht nützlich).
- Nutzen Sie tägliche Splines der momentanen und abnehmenden Prognosewerte von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.40...v4.0.41

Version 4.0.40

- Interpolierte Prognose für 0/30/60 Strom und Energie in X Stunden von @autoSteve
- Stellen Sie sicher, dass das Konfigurationsverzeichnis immer relativ zum Installationsort ist (von @autoSteve).
- Beispielhafte PV-Diagrammverbesserungen von @gcoan

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.39...v4.0.40

Version 4.0.39

- Aktualisierungen der Sensorbeschreibungen und Änderung einiger Sensornamen durch @isorin (Möglicherweise Probleme mit der Benutzeroberfläche/Automatisierungen usw., falls diese Sensoren verwendet werden. Leistungsaufnahme in 30/60 Minuten und benutzerdefinierter X-Stunden-Sensor.)
- Abhängigkeit von der SciPy-Bibliothek entfernen (von @autoSteve)
- Füge detaillierte Konfigurationsoptionen für Attribute von @autoSteve hinzu

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.38...v4.0.39

Version 4.0.38

- Füge die wichtigsten Solcast-Konzepte und ein Beispieldiagramm zur PV-Erzeugung zur Readme-Datei hinzu (von @gcoan)
- PCHIP-Spline zur Prognose des Restbetrags hinzufügen von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.37...v4.0.38

Version 4.0.37

- Attributbenennung ändern, um "pv_" zu entfernen (von @autoSteve; Hinweis: Dies führt zu Problemen, wenn die neuen Attribute bereits in Vorlagen/Automatisierungen verwendet werden).
- Rundung von Sensorattributen #51 von @autoSteve
- Verbesserung der Ausnahmebehandlung für den Prognoseabruf durch @autoSteve
- Weitere Verbesserung der Ausnahmebehandlung für den Prognoseabruf durch @autoSteve
- Ausnahme durch Warnung ersetzen #74 von @autoSteve
- Wiederholen eines unerklärten Cache-/Datenladevorgangs durch @autoSteve
- Weniger aufdringliche Debug-Protokollierung von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.36...v4.0.37

Version 4.0.36

- (Verbesserung) Zusätzliche Sensorattribute (Schätzung/Schätzung10/Schätzung90) und Verbesserungen der Protokollierung von @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.35...v4.0.36

Version 4.0.35

- (Verbesserung) Aufschlüsselung der prognostizierten Wattzahl und Zeit einzelner Standorte als Attribute von @autoSteve
- Protokolliere keine Aktualisierung der Optionsversion, wenn @autoSteve keine Aktualisierung benötigt.
- Informationen zum Erhalt des Oziee-Verlaufs und der Konfiguration im Banner hinzufügen (von @iainfogg)

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.34...v4.0.35

Version 4.0.34

- Korrigiere query_forecast_data, sodass von @isorin kurzfristige historische Prognosen zurückgegeben werden.
- Bei Fehlern der Rooftop-/Nutzungs-API-Aufrufe wird beim Neuladen sofort auf den Cache zurückgegriffen, was die Startzeit verkürzen kann (von @autoSteve).
- Bei einem Timeout des asynchronen Aufrufs von `sites get` wird, falls vorhanden, auf den Cache zurückgegriffen (von @autoSteve).
- Viele Verbesserungen im Logging-Prozess von @autoSteve
- Der Website-Cache wird manchmal fälschlicherweise mit dem angehängten API-Schlüssel erstellt, obwohl nur ein API-Schlüssel vorhanden ist (von @autoSteve).
- Schwärzung der Breiten-/Längengradangaben in den Debug-Protokollen durch @autoSteve
- Wahrscheinliche Beseitigung der „Zähl“-Warnungen durch @autoSteve
- Behebung des Wiederholungsmechanismus für die API-Nutzung durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.33...v4.0.34

Version 4.0.33

- Leistungsverbesserungen für Sensoraktualisierungen von @isorin, einschließlich:
    - Das Aktualisierungsintervall der Sensoren wurde auf 5 Minuten reduziert.
    - Teilen Sie die Sensoren in zwei Gruppen ein: Sensoren, die alle 5 Minuten aktualisiert werden müssen, und Sensoren, die nur aktualisiert werden müssen, wenn die Daten aktualisiert werden oder sich das Datum ändert (Tageswerte).
    - Probleme beim Entfernen älterer Prognosen (älter als 2 Jahre) behoben, fehlerhafter Code
    - Die Funktionalität der Prognosen wird verbessert. Beispielsweise wird „forecast_remaining_today“ alle 5 Minuten aktualisiert, indem die verbleibende Energie aus dem aktuellen 30-Minuten-Intervall berechnet wird. Gleiches gilt für die Sensoren „jetzt/nächste Stunde“.
- Schwärzung des Solcast-API-Schlüssels in den Protokollen durch @isorin
- Die Änderung #54 von @autoSteve in Oziee '4.0.23' async_update_options, die zu Problemen mit der Aktualisierungsdämpfung führte, wurde rückgängig gemacht.

Ein Kommentar von @isorin: „ *Ich verwende forecast_remaining_today, um den Zeitpunkt zu bestimmen, zu dem die Akkus geladen werden sollen, damit sie abends einen vordefinierten Ladezustand erreichen. Mit meinen Änderungen ist das möglich.* “

Dazu sage ich: Gut gemacht.

Neue Mitwirkende

- @isorin hat seinen ersten Beitrag in https://github.com/BJReplay/ha-solcast-solar/pull/45 geleistet.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.32...v4.0.33

Version 4.0.32

- Bugfix: Unabhängiger API-Nutzungszähler für jedes Solcast-Konto von @autoSteve
- Bugfix: Alle Caches werden nun plattformübergreifend in /config/ gespeichert (behebt Probleme bei Docker-Bereitstellungen) #43 von @autoSteve
- Verbesserung der Protokollierung von Abruf-/Wiederholungsversuchen der Prognose durch @autoSteve
- Unterdrückung aufeinanderfolgender Prognoseabrufe innerhalb von fünfzehn Minuten (behebt seltsame Mehrfachabrufe, falls ein Neustart genau dann erfolgt, wenn die Automatisierung für den Abruf ausgelöst wird) von @autoSteve
- Problemumgehung: Fehler verhindern, wenn „tally“ bei einem Wiederholungsversuch durch #autoSteve nicht verfügbar ist
- Behebung des Problems, dass ältere HA-Versionen die Versionsangabe für async_update_entry() nicht erkannten (#40 von autoSteve).

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.0.32

Version 4.0.31

- Dokumentation: Änderungen an der README.md-Datei
- Dokumentation: Hinweise zur Fehlerbehebung hinzufügen.
- Dokumentation: Änderungshinweise aus info.md in README.md zusammenführen
- Dokumentation: HACS soll so konfiguriert werden, dass die Datei README.md angezeigt wird.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.30...v4.0.31

v4.0.30

- Fehlerbehebung: Unterstützung für das Caching mehrerer Solcast-Kontoseiten
- Fehlerbehebung: Der Wiederholungsmechanismus, der bei erfolgreicher Erfassung von Dachstandorten fehlerhaft war, funktionierte nicht.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.29...v4.0.30

Version 4.0.29

- Bugfix: API-Nutzungs-Cache wird bei jeder erfolgreichen Abfrage geschrieben (von @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/29)
- Fehlerbehebung: Standardmäßiges API-Limit auf 10 gesetzt, um den Fehler beim ersten Aufruf zu beheben (von @autoSteve).
- Erhöhung der GET-Wiederholungsversuche von zwei auf drei durch @autoSteve

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.28...v4.0.29

Version 4.0.28

- Wiederholungsversuche für Dachstandorte hinzugefügt (Sammlung #12 von @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/26)
- Änderungen in der Datei „full info.md“ seit Version 4.0.25
- Die meisten Änderungen von Oziee in Version 4.0.23, die von @autoSteve vorgenommen wurden, wurden wieder übernommen.
- Zwischengespeicherte Daten beibehalten, wenn das API-Limit erreicht ist

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.27...v4.0.28

Neuer Mitarbeiter

- @autoSteve hat in den letzten Tagen einen großen Beitrag geleistet – er hat einen Sponsoren-Button auf seinem Profil, also scheut euch nicht, ihn anzuklicken!

Version 4.0.27

- Dokumentation: Aktualisierung der Datei info.md durch @Kolbi in https://github.com/BJReplay/ha-solcast-solar/pull/19
- Verwenden Sie aiofiles mit async open, await data_file von @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/21
- Unterstützung für async_get_time_zone() hinzugefügt von @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/25

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.26...v4.0.27

Neue Mitwirkende

- @Kolbi hat seinen ersten Beitrag in https://github.com/BJReplay/ha-solcast-solar/pull/19 geleistet.
- @autoSteve hat seinen ersten Beitrag in https://github.com/BJReplay/ha-solcast-solar/pull/21 geleistet.

Version 4.0.26

- Behebt #8, #9 und #10 – Meine HA-Button-Kategorie von @mZ738 in https://github.com/BJReplay/ha-solcast-solar/pull/11
- README.md wurde von @wimdebruyn in https://github.com/BJReplay/ha-solcast-solar/pull/5 aktualisiert.
- Bereiten Sie sich auf die neue Version von @BJReplay unter https://github.com/BJReplay/ha-solcast-solar/pull/13 vor.

Vollständiges Änderungsprotokoll: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.25...v4.0.26

Neue Mitwirkende

- @mZ738 hat seinen ersten Beitrag in https://github.com/BJReplay/ha-solcast-solar/pull/11 geleistet.
- @wimdebruyn hat seinen ersten Beitrag in https://github.com/BJReplay/ha-solcast-solar/pull/5 geleistet.

Version 4.0.25

- HACS-Einreichung

Version 4.0.24

- Weitere Änderungen zur Entfernung der beim ersten Mal übersehenen Links zu https://github.com/oziee.
- Weitere Änderungen zur Vorbereitung der Einreichung bei HACS

Version 4.0.23

- Besitzer geändert zu @BJReplay
- Das GitHub-Repository wurde in https://github.com/BJReplay/ha-solcast-solar geändert.

Version 4.0.22

- Diesmal ist der Wettersensor ausgefallen... und die UTC-Neustart-Funktion funktioniert.
- (*) Eine Konfigurationsoption zum Festlegen eines Grenzwerts für Wechselrichter mit überdimensionierten Solaranlagen wurde hinzugefügt. *99,9999999 % der Benutzer werden diese Option nie benötigen (0,00000001 % sind @CarrapiettM).

Version 4.0.21

- Der Wettersensor wurde entfernt, da er ständig Fehler verursachte.

Version 4.0.20

- Der Informationsfehler für `solcast_pv_forecast_forecast_today (<class 'custom_components.solcast_solar.sensor.SolcastSensor'>) is using state class 'measurement' which is impossible considering device class ('energy')`
- Die Abfrage um Mitternacht UTC wurde entfernt und durch eine auf Null gesetzte Abfrage ersetzt, um die Belastung des Solcast-Systems zu reduzieren. ⚠️ Um die Auswirkungen auf das Solcast-Backend zu minimieren, bittet Solcast die Benutzer, ihre Automatisierungen für die Abfrage mit zufälligen Minuten- und Sekundenwerten zu konfigurieren. Wenn Sie beispielsweise um 10:00 Uhr abfragen, stellen Sie den Wert auf 10:04:10 ein, damit nicht alle Benutzer gleichzeitig die Dienste abfragen.

Version 4.0.19

- Problem behoben: API-Limit/Nutzung wird bei Zurücksetzung nicht aktualisiert (HA-Benutzeroberfläche wird nicht aktualisiert).

Version 4.0.18

- Der Wert des Wettersensors bleibt nicht erhalten.
- API-Limit und Nutzungssensoren um Mitternacht UTC zurücksetzen (Nutzung zurücksetzen)

Version 4.0.17

- Aktualisierte slowakische Übersetzung, danke an @misa1515
- hinzugefügter Sensor für Solcast-Wetterbeschreibung

Version 4.0.16

- Die Idee von @Zachoz, eine Einstellung zur Auswahl des Solcast-Schätzfeldwerts für die Vorhersageberechnungen hinzuzufügen (Schätzung, Schätzung10 oder Schätzung90), wurde hinzugefügt. ESTIMATE – Standardvorhersagen; ESTIMATE10 = Vorhersage 10 – Szenario: stärker bewölkt als erwartet
     ESTIMATE90 = Prognose 90 – weniger bewölkt als erwartet

Version 4.0.15

- Es wurde ein benutzerdefinierter Sensor für die „Nächsten X Stunden“ hinzugefügt. Sie wählen die Anzahl der zu berechnenden Stunden als Sensorwert aus.
- Französische Übersetzung hinzugefügt, vielen Dank an @Dackara
- Es wurden einige Sensoren hinzugefügt, die in die HA-Statistikdaten einbezogen werden sollen.

Version 4.0.14

- Die Attributwerte der Dachstandorte wurden geändert, sodass keine Markierungen zu den Karten hinzugefügt werden (HA fügt Elemente automatisch zur Karte hinzu, wenn Attribute Breiten-/Längenwerte enthalten).
- Urdu hinzugefügt, vielen Dank an @yousaf465

Version 4.0.13

- Slowakische Übersetzung hinzugefügt, vielen Dank an @misa1515
- Verlängerung des Timeouts für die Abfrageverbindung von 60 Sekunden auf 120 Sekunden
- Es wurden weitere Debug-Ausgabepunkte zur Datenprüfung hinzugefügt.
- Das neue Attribut `dataCorrect` für Prognosedaten gibt True oder False zurück, je nachdem, ob die Daten für den jeweiligen Tag vollständig sind.
- Die Fehlermeldung `0 of 48` Debug-Meldungen für die 7-Tage-Vorhersage wurden entfernt, da die Daten für den 7. Tag unvollständig sind, wenn die API nicht um Mitternacht abgefragt wird (Beschränkung der maximalen Anzahl von Datensätzen, die Solcast zurückgibt).

Version 4.0.12

- HA 2023.11 Beta erzwingt, dass Sensoren nicht unter `Configuration` aufgeführt werden. Die Dachsensoren wurden in `Diagnostic` verschoben.

Version 4.0.11

- bessere Verarbeitung bei unvollständigen Daten für einige Sensoren

Version 4.0.10

- Behebung von Problemen beim Ändern eines API-Schlüssels, nachdem dieser bereits festgelegt wurde.

Version 4.0.9

- Neuer Service zur Aktualisierung der stündlichen Dämpfungsfaktoren der Prognose

Version 4.0.8

- Polnische Übersetzung hinzugefügt, vielen Dank an @home409ca
- Neue `Dampening` zur Solcast-Integrationskonfiguration hinzugefügt

Version 4.0.7

- Verbesserte Handhabung, wenn die Solcast-Website keine korrekten API-Daten zurückgibt

Version 4.0.6

- Es wird ein Fehler aufgrund von Division durch Null ausgegeben, wenn keine Daten zurückgegeben werden.
- Der verbleibende Prognosewert für heute wurde fixiert. Die Berechnung beinhaltet nun die aktuelle 30-Minuten-Blockprognose.

Version 4.0.5

- PR #192 – aktualisierte deutsche Übersetzung… danke @florie1706
- Die Vorhersage `Remaining Today` wurde korrigiert. Sie verwendet nun auch die 30-Minuten-Intervalldaten.
- Problem behoben: `Download diagnostic` führte beim Anklicken zu einem Fehler.

Version 4.0.4

- Der Serviceaufruf `query_forecast_data` zum Abfragen der Prognosedaten wurde abgeschlossen. Er gibt eine Liste von Prognosedaten anhand eines Datums-/Zeitbereichs (Start - Ende) zurück.
- Und das ist alles ... es sei denn, HA nimmt grundlegende Änderungen vor oder es gibt einen schwerwiegenden Fehler in Version 4.0.4, dann ist dies das letzte Update.

Version 4.0.3

- Die deutsche Version wurde dank @florie1706 (PR#179) aktualisiert und alle anderen Lokalisierungsdateien wurden entfernt.
- Das neue Attribut `detailedHourly` wurde jedem Sensor für die Tagesvorhersage hinzugefügt und listet stündliche Vorhersagen in kWh auf.
- Wenn Daten fehlen, zeigen die Sensoren zwar weiterhin etwas an, aber im Debug-Protokoll wird ausgegeben, dass dem Sensor Daten fehlen.

Version 4.0.2

- Die Sensornamen **haben** sich geändert! Dies liegt an den Lokalisierungszeichenfolgen der Integration.
- Die Dezimalgenauigkeit für die morgige Vorhersage wurde von 0 auf 2 geändert.
- Fehlende Daten in der 7-Tage-Vorhersage, die zuvor ignoriert worden waren, wurden korrigiert.
- Neuer Sensor `Power Now` hinzugefügt
- Neuer Sensor hinzugefügt: `Power Next 30 Mins`
- Neuer Sensor `Power Next Hour` hinzugefügt
- Lokalisierung für alle Objekte in der Integration hinzugefügt. Vielen Dank an @ViPeR5000 für den Anstoß zu diesem Thema (Google Translate wurde verwendet; falls Fehler gefunden werden, bitte Pull Request senden, damit ich die Übersetzungen aktualisieren kann).

Version 4.0.1

- Neu basierend auf Version 3.0.55
- Speichert die Prognosedaten der letzten 730 Tage (2 Jahre).
- Bei einigen Sensoren wurden die Geräteklasse und die native Maßeinheit auf den korrekten Typ aktualisiert.
- Die Anzahl der API-Abfragen wird direkt von Solcast gelesen und nicht mehr berechnet.
- Automatisches Abfragen entfällt. Jeder Nutzer muss nun selbst eine Automatisierung einrichten, um Daten bei Bedarf abzurufen. Grund dafür ist, dass viele Nutzer nur noch 10 API-Aufrufe pro Tag durchführen.
- Die Änderungen an der UTC-Zeit wurden entfernt, und die Solcast-Daten bleiben unverändert, sodass die Zeitzonendaten bei Bedarf geändert werden können.
- Aufgrund der Umbenennung des Sensors gingen die Verlaufseinträge verloren. Die HA-Historie wird nicht mehr verwendet; die Daten werden stattdessen in der Datei solcast.json gespeichert.
- Der Aktualisierungsdienst wurde entfernt. Die aktuellen Daten von Solcast werden nicht mehr abgefragt (sie werden bei der Erstinstallation verwendet, um vergangene Daten zu erhalten, damit die Integration funktioniert und ich keine Fehlerberichte erhalte, da Solcast keine Daten für den gesamten Tag liefert, sondern nur Daten ab dem Zeitpunkt des Aufrufs).
- Viele der Protokollmeldungen wurden aktualisiert und lauten nun Debug-, Info-, Warnungs- oder Fehlermeldungen.
- Bei einigen Sensoren **könnten** möglicherweise keine zusätzlichen Attributwerte mehr vorhanden sein oder Attributwerte könnten umbenannt oder in die gespeicherten Daten geändert worden sein.
- Ausführlichere Diagnosedaten, die bei Bedarf zur Verfügung gestellt werden können, um bei der Fehlersuche zu helfen.
- Ein Teil der Arbeit von @rany2 wurde nun integriert.

Version 3.1.x wurde entfernt.

- Zu viele Nutzer konnten die Leistungsfähigkeit dieser Version nicht bewältigen.
- Version 4.xx ersetzt die Versionen 3.0.55 bis 3.1.x und enthält neue Änderungen.

Version 3.0.47

- Das Attribut „Wochentagsname“ wurde für Sensorvorhersagen hinzugefügt. Die Namen „heute“, „morgen“ und „D3…7“ können über die Vorlage {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_tomorrow', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D3', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D4', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D5', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D6', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D7', 'dayname') }} ausgelesen werden.

Version 3.0.46

- Mögliches MariaDB-Problem – mögliche Lösung

Version 3.0.45

- Vorabveröffentlichung
- wird derzeit getestet
- Es schadet nichts, wenn du es installierst.

Version 3.0.44

- Vorabveröffentlichung
- bessere Diagnosedaten
- nur zum Testen
- Es schadet nichts, wenn du es installierst.

Version 3.0.43

- Vorabversion – nicht zur Verwendung!
- Nicht installieren :) Nur zum Testen

Version 3.0.42

- Das Problem wurde behoben, dass der Dienst zur Aktualisierung von Prognosen nicht mehr zweimal aufgerufen wurde.

Version 3.0.41

- Die Protokollierung wurde überarbeitet und neu formuliert. Mehr Debug-, Informations- und Fehlerprotokollierung.
- Der API-Nutzungszähler wurde nicht aufgezeichnet, als er um Mitternacht UTC auf Null zurückgesetzt wurde.
- Es wurde ein neuer Service hinzugefügt, über den Sie die Ist-Daten von Solcast für die Vorhersagen aktualisieren können.
- Die Versionsinformationen wurden der Integrations-UI hinzugefügt.

Version 3.0.40

- Jemand hat in Version 3.0.39 ungenutzten Code hinterlassen, der Probleme verursacht.

Version 3.0.39

- entfernte Versionsinformationen

Version 3.0.38

- Fehler in Version 3.0.37 behoben (Sensoraktualisierung)

Version 3.0.37

- Stellen Sie sicher, dass die stündlichen Sensoren aktualisiert werden, wenn die automatische Abfrage deaktiviert ist.

Version 3.0.36

- Beinhaltet alle Vorab-Artikel
- Aktuelle, präzise Daten aus der Vergangenheit werden nun nur noch mittags und zur letzten Stunde des Tages über die API abgefragt (also nur zweimal täglich).

Version 3.0.35 – Vorabversion

- Das Timeout für die Internetverbindung wurde auf 60 Sekunden verlängert.

Version 3.0.34 – Vorabversion

- Es wurde ein Dienst hinzugefügt, der die alte solcast.json-Datei löscht, um einen sauberen Neustart zu ermöglichen.
- Gibt leere Energiediagrammdaten zurück, wenn ein Fehler bei der Informationsgenerierung auftritt.

Version 3.0.33

- Sensoren für die Vorhersagetage 3, 4, 5, 6 und 7 hinzugefügt

Version 3.0.32

- überarbeitete Anforderungen an den Aufruf der HA-Setup-Funktion
- Habe etwas anderen Code mit Tippfehlern überarbeitet, um die Rechtschreibung zu korrigieren... keine große Sache.

Version 3.0.30

- Einige Änderungen des PRs von @696GrocuttT wurden in diese Version integriert.
- Behobener Code im Zusammenhang mit der Ausnutzung aller zulässigen API-Kontingente
- Dieses Release wird höchstwahrscheinlich den aktuellen API-Zähler durcheinanderbringen, aber nach dem Zurücksetzen des UTC-Zählers wird die API-Zählung wieder einwandfrei funktionieren.

Version 3.0.29

- Der Sensor für die Spitzenzeit heute/morgen wurde von Datum/Uhrzeit auf Uhrzeit umgestellt.
- Die Einheit für die Spitzenwertmessung wurde wieder auf Wh umgestellt, da der Sensor die für die Stunde prognostizierten Spitzen-/Maximalstunden angibt.
- Es wurde eine neue Konfigurationsoption für die Integration hinzugefügt, um die automatische Datenabfrage zu deaktivieren. Benutzer können dann ihre eigene Automatisierung einrichten, um Daten nach Belieben abzurufen (hauptsächlich, weil Solcast das API-Limit für neue Konten auf nur noch 10 pro Tag reduziert hat).
- Der API-Zähler zeigt nun den Gesamtverbrauch anstelle des verbleibenden Kontingents an, da manche Nutzer 10, andere 50 Kontingente haben. Die Meldung „API-Kontingent überschritten“ erscheint, wenn kein Kontingent mehr verfügbar ist.

Version 3.0.27

- Einheit für Spitzenwertmessung geändert #86 Danke an Ivesvdf
- einige weitere kleinere Textänderungen für Protokolle
- Geänderter Serviceanruf, danke 696GrocuttT
- einschließlich der Behebung von Problem Nr. 83

Version 3.0.26

- Test der Fehlerbehebung für Problem #83

Version 3.0.25

- PR für 3.0.24 entfernt – verursachte Fehler im Prognosediagramm
- Behoben: HA 2022.11 kann keine Prognose zum Solar-Dashboard hinzufügen

Version 3.0.24

- Zusammengeführter PR von @696GrocuttT

Version 3.0.23

- Es wurde weiterer Debug-Log-Code hinzugefügt.
- Der Dienst zur Aktualisierung der Prognose wurde hinzugefügt.

Version 3.0.22

- Es wurde weiterer Debug-Log-Code hinzugefügt.

Version 3.0.21

- Es wurden weitere Debug-Protokolle für detailliertere Informationen hinzugefügt.

Version 3.0.19

- BEHOBEN: coordinator.py", Zeile 133, in update_forecast für update_callback in self._listeners: RuntimeError: Wörterbuchgröße hat sich während der Iteration geändert
- Diese Version benötigt jetzt HA 2022.7 oder höher.

Version 3.0.18

- geänderte Berechnungen des API-Zähler-Rückgabewerts

Version 3.0.17

- Stellen Sie die Abfragezeit der API auf 10 Minuten nach der vollen Stunde ein, um der Solcast-API Zeit zur Berechnung der Satellitendaten zu geben.

Version 3.0.16

- Die API-Abfrage wurde so angepasst, dass im Laufe des Tages gelegentlich aktuelle Daten abgerufen werden.
- Vollständiger Pfad zur Datendatei hinzugefügt – danke OmenWild

Version 3.0.15

- Funktioniert sowohl in der Betaversion 2022.6 als auch in der Betaversion 2022.7.

Version 3.0.14

- Behebt HA 2022.7.0b2-Fehler (scheint zu funktionieren :) )

Version 3.0.13

- Die zuvor grafisch dargestellten Daten wurden nicht um Mitternacht Ortszeit zurückgesetzt.
- fehlender asyncio-Import

Version 3.0.12

- Die grafisch dargestellten Daten für Woche/Monat/Jahr waren nicht sortiert, daher war die Grafik unübersichtlich.

Version 3.0.11

- Timeout für Solcast-API-Serververbindungen hinzugefügt.
- Die Diagrammdaten der letzten 7 Tage wurden dem Energie-Dashboard hinzugefügt (funktioniert nur, wenn Sie Daten aufzeichnen).

Version 3.0.9

- **Benutzer, die von Version 3.0.5 oder älter aktualisieren, müssen die Datei „solcast.json“ im Verzeichnis HA&gt;config löschen, um Fehler zu vermeiden.**
- Sensoren wurden mit dem Präfix „solcast_“ umbenannt, um die Benennung zu vereinfachen.
- **Aufgrund der Namensänderung werden Sensoren in der Integration doppelt angezeigt. Diese werden in der Liste ausgegraut oder mit Werten wie „Unbekannt“ oder „Nicht verfügbar“ usw. angezeigt. Löschen Sie diese alten Sensoren einfach einzeln aus der Integration.**

Version 3.0.6

- **Benutzer, die von Version 3.0.x aktualisieren, müssen die Datei „solcast.json“ im Verzeichnis HA&gt;config löschen.**
- Viele kleine Fehler und Probleme wurden behoben.
- Es wurde die Möglichkeit hinzugefügt, mehrere Solcast-Konten hinzuzufügen. Trennen Sie dazu einfach die API-Schlüssel in der Integrationskonfiguration durch Kommas.
- Der API-Zähler zeigt die verbleibenden API-Einheiten an, nicht die Anzahl der verwendeten Einheiten.
- Die Daten der „tatsächlichen Vorhersage“ werden nun nur noch einmal abgerufen, und zwar beim letzten API-Aufruf bei Sonnenuntergang. Alternativ kann dies auch während der ersten Ausführung der Integrationsinstallation erfolgen.
- Die Prognosedaten werden weiterhin stündlich zwischen Sonnenaufgang und Sonnenuntergang sowie einmal täglich um Mitternacht abgerufen. *Der alte API-Zähler-Sensor kann gelöscht werden, da er nicht mehr benötigt wird.*

Version 3.0.5 Beta

- Die Sensorwerte für „diese Stunde“ und „nächste Stunde“ wurden korrigiert.
- Die API-Abfrage wird verlangsamt, wenn mehr als ein Dach abgefragt werden soll.
- Korrigieren Sie die Diagrammdaten der ersten Stunde.
- Möglicherweise RC1? Wir werden sehen.

Version 3.0.4 Beta

- Fehlerbehebungen.

Version 3.0

- komplett neu geschrieben

Frühere Daten sind nicht verfügbar.




## Credits

Abgewandelt nach den großen Werken von

- oziee/ha-solcast-solar
- @rany2 - ranygh@riseup.net
- dannerph/homeassistant-solcast
- cjtapper/solcast-py
- home-assistant-libs/forecast_solar


