# Intégration des prévisions solaires photovoltaïques HA Solcast

<!--[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)-->

[](https://github.com/custom-components/hacs)![badge hacs](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)![Publication GitHub](https://img.shields.io/github/v/release/BJReplay/ha-solcast-solar?style=for-the-badge)[](https://github.com/BJReplay/ha-solcast-solar/releases/latest)![téléchargements hacs](https://img.shields.io/github/downloads/BJReplay/ha-solcast-solar/latest/total?style=for-the-badge)![Licence GitHub](https://img.shields.io/github/license/BJReplay/ha-solcast-solar?style=for-the-badge)![Activité de commit sur GitHub](https://img.shields.io/github/commit-activity/y/BJReplay/ha-solcast-solar?style=for-the-badge)![Entretien](https://img.shields.io/maintenance/yes/2026?style=for-the-badge)

**Languages:** [🇦🇺 English](https://github.com/BJReplay/ha-solcast-solar/blob/main/README.md) | [🇩🇪 Deutsch](https://github.com/BJReplay/ha-solcast-solar/blob/main/README_de.md) | [🇫🇷 Français](https://github.com/BJReplay/ha-solcast-solar/blob/main/README_fr.md)

## Préambule

Ce composant personnalisé intègre les prévisions photovoltaïques Solcast pour les amateurs dans Home Assistant (https://www.home-assistant.io).

Il permet la visualisation des prévisions solaires dans le tableau de bord Énergie et prend en charge l'amortissement flexible des prévisions, l'application d'une limite stricte pour les systèmes PV surdimensionnés, un ensemble complet d'entités de capteurs et de configuration, ainsi que des attributs de capteurs contenant tous les détails des prévisions pour prendre en charge l'automatisation et la visualisation.

Il s'agit d'une intégration aboutie, avec une communauté active et des développeurs réactifs.

Cette intégration n'est ni créée, ni maintenue, ni approuvée, ni validée par Solcast.

> [!TIP]
>
> #### Instructions de support
>
> Veuillez consulter la [FAQ](https://github.com/BJReplay/ha-solcast-solar/blob/main/FAQ.md) pour les problèmes et solutions courants, consulter les [discussions](https://github.com/BJReplay/ha-solcast-solar/discussions) épinglées et actives, et examiner les [problèmes](https://github.com/BJReplay/ha-solcast-solar/issues) ouverts avant de créer un nouveau problème ou une nouvelle discussion.
>
> Ne publiez pas de commentaires du type « Moi aussi » sur les problèmes existants (mais n'hésitez pas à voter pour ou à vous abonner aux notifications concernant les problèmes où vous rencontrez le même souci) et ne présumez pas que si vous avez une erreur similaire, il s'agit forcément de la même. À moins que l'erreur ne soit identique, il ne s'agit probablement pas de la même.
>
> Demandez-vous toujours si vous devez signaler un bug dans l'intégration ou si vous avez besoin d'aide pour la configuration. Si vous avez besoin d'assistance, vérifiez s'il existe une discussion qui répond à votre question, ou posez votre question dans la section Discussion.
>
> Si vous pensez avoir trouvé un problème qui est un bug, veuillez vous assurer de suivre les instructions du modèle de rapport de problème lorsque vous le signalez.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

> [!NOTE]
>
> Cette intégration remplace l'ancienne intégration oziee/ha-solcast-solar, qui n'est plus développée et a été supprimée. Désinstaller la version Oziee puis installer celle-ci, ou simplement télécharger cette dernière par-dessus l'ancienne, conservera l'historique et la configuration. Si vous **avez désinstallé** l'intégration Oziee puis installé celle-ci, vous devrez resélectionner Solcast Solar comme source de prévisions pour votre tableau de bord Énergie.

# Table des matières

1. [Concepts clés d'intégration de Solcast](#key-solcast-integration-concepts)
2. [exigences de Solcast](#solcast-requirements)
3. [Installation](#installation)
    1. [HACS recommandé](#hacs-recommended)
    2. [Installation manuelle dans HACS](#installing-manually-in-hacs)
    3. [Installation manuelle (sans utiliser HACS)](#installing-manually-(not-using-hacs))
    4. [Versions bêta](#beta-versions)
4. [Configuration](#configuration)
    1. [Mise à jour des prévisions](#updating-forecasts)
        1. [Mise à jour automatique des prévisions](#auto-update-of-forecasts)
        2. [Utilisation d'une automatisation HA pour mettre à jour les prévisions](#using-an-ha-automation-to-update-forecasts)
    2. [Configurer les paramètres du tableau de bord énergétique HA](#set-up-ha-energy-dashboard-settings)
5. [Interagir](#interacting)
    1. [Capteurs](#sensors)
    2. [Attributs](#attributes)
    3. [Actes](#actions)
    4. [Configuration](#configuration)
    5. [Diagnostique](#diagnostic)
6. [Configuration avancée](#advanced-configuration)
    1. [Configuration d'amortissement](#dampening-configuration)
        1. [Amortissement automatisé](#automated-dampening)
        2. [simple amortissement horaire](#simple-hourly-dampening)
        3. [Amortissement granulaire](#granular-dampening)
        4. [Lecture des valeurs prévisionnelles dans un système automatisé](#reading-forecast-values-in-an-automation)
        5. [valeurs d'amortissement de lecture](#reading-dampening-values)
    2. [configuration des attributs du capteur](#sensor-attributes-configuration)
    3. [Configuration de limite stricte](#hard-limit-configuration)
    4. [Configuration des sites exclus](#excluded-sites-configuration)
    5. [options de configuration avancées](#advanced-configuration-options)
7. [Capteurs de gabarit d'exemple](#sample-template-sensors)
8. [Exemple de graphique Apex pour tableau de bord](#sample-apex-chart-for-dashboard)
9. [Problèmes connus](#known-issues)
10. [Dépannage](#troubleshooting)
11. [Suppression complète de l'intégration](#complete-integration-removal)
12. [Changements](#Changes)

## Concepts clés d'intégration de Solcast

Le service Solcast génère des prévisions de production d'énergie solaire photovoltaïque à partir d'aujourd'hui et jusqu'à treize jours plus tard, soit un total de quatorze jours. Les sept premières prévisions sont affichées par l'intégration sous forme de capteur distinct, la valeur correspondant à la production solaire totale prévue pour chaque jour. Les prévisions pour les jours suivants ne sont pas affichées par les capteurs, mais peuvent être visualisées sur le tableau de bord Énergie.

Des capteurs séparés sont également disponibles et contiennent la puissance de production de pointe prévue, l'heure de production de pointe et diverses prévisions pour l'heure suivante, les 30 minutes suivantes, et plus encore.

Si plusieurs panneaux solaires sont installés sur des toits orientés différemment, vous pouvez les configurer dans votre compte Solcast comme des « sites de toiture » distincts, avec des paramètres d'azimut, d'inclinaison et de production maximale différents (deux sites maximum pour un compte amateur gratuit). Les prévisions de ces sites sont ensuite combinées pour former les valeurs des capteurs intégrés et les données de prévision du tableau de bord Énergie.

Solcast produit trois estimations de production solaire pour chaque période d'une demi-heure, et ce, pour tous les jours prévus.

- La prévision « centrale », à 50 % ou la plus susceptible de se produire est présentée comme l' `estimate` issue de l'intégration.
- « 10 % » ou 1 sur 10 prévision « pire cas » supposant une couverture nuageuse plus importante que prévu, exposée comme `estimate10` .
- « 90 % » ou 1 sur 10, prévision « dans le meilleur des cas » supposant une couverture nuageuse inférieure aux prévisions, exposée sous la forme `estimate90` .

Le détail de ces différentes estimations de prévision se trouve dans les attributs des capteurs, qui comprennent des intervalles journaliers de 30 minutes et des intervalles horaires calculés tout au long de la journée. Des attributs distincts permettent de sommer les estimations disponibles ou de les ventiler par site Solcast. (Cette intégration référence généralement un site Solcast par son « identifiant de ressource de site », disponible sur le site web de Solcast : https://toolkit.solcast.com.au/)

Le tableau de bord Énergie de Home Assistant est alimenté par les données historiques fournies par l'intégration, conservées pendant deux ans maximum. (L'historique des prévisions n'est pas stocké dans les statistiques de Home Assistant, mais dans un fichier cache `json` géré par l'intégration.) L'historique affiché peut correspondre aux prévisions passées ou aux données « estimées réelles », selon une option de configuration.

Il est possible de modifier les prévisions pour tenir compte des ombrages prévisibles à certains moments de la journée, soit automatiquement, soit en définissant des coefficients d'atténuation pour des périodes horaires ou semi-horaires. Une limite stricte peut également être fixée pour les installations solaires surdimensionnées, lorsque la production attendue ne doit pas dépasser la puissance maximale de l'onduleur. Ces deux mécanismes sont les seuls moyens de modifier les données de prévision de Solcast.

Solcast produit également des données historiques estimées. Celles-ci sont généralement plus précises qu'une prévision, car elles s'appuient sur l'imagerie satellite haute résolution, les données météorologiques et d'autres observations climatiques (comme la vapeur d'eau et le smog) pour calculer les estimations. La fonction d'atténuation automatique intégrée peut utiliser ces données estimées et les comparer à l'historique de production afin de modéliser une réduction de la production prévue et de tenir compte des variations d'ombrage locales. Ces données estimées peuvent également être visualisées sur le tableau de bord Énergie, que l'atténuation automatique soit activée ou non.

> [!NOTE]
>
> Solcast a modifié les limites de son API. Les nouveaux créateurs de comptes amateurs sont autorisés à effectuer un maximum de 10 appels API par jour. Les utilisateurs amateurs existants conservent jusqu'à 50 appels par jour.

## exigences de Solcast

Inscrivez-vous pour obtenir une clé API (https://solcast.com/).

> Solcast peut mettre jusqu'à 24 heures pour créer le compte.

Configurez correctement vos sites d'installation sur les toits sur `solcast.com` .

Supprimez tous les sites d'exemple de votre tableau de bord Solcast (consultez [la section « Problèmes connus »](#known-issues) pour des exemples de sites d'exemple et le problème qui pourrait survenir si vous ne les supprimez pas).

Copiez la clé API pour l'utiliser avec cette intégration (voir [la configuration](#Configuration) ci-dessous).

Il est essentiel de bien configurer votre site Solcast. Utilisez l'indication « Orientation du site » pour vérifier que l'azimut est correct ; une erreur de configuration peut entraîner un décalage des prévisions, pouvant atteindre une heure en cours de journée.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png" width="600">

L'azimut n'est *pas* défini comme une valeur de 0 à 359 degrés, mais plutôt de 0 à 180 pour une orientation ouest, ou de *0* à -179 pour une orientation est. Cette valeur correspond à l'angle, en degrés, par rapport au nord, le signe étant ouest ou est. En cas de doute, une petite recherche s'impose.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png" width="300">

Une méthode traditionnelle, mais parfois efficace, consiste à obtenir une image satellite de votre domicile sur Google Maps, orientée vers le nord, et à mesurer l'azimut à l'aide d'un rapporteur en plastique à 180°. Placez le bord droit du rapporteur sur l'axe nord-sud de l'écran et son centre sur le côté d'un panneau représentatif. Comptez les degrés à partir du nord. Pour une orientation ouest ou est, retournez le rapporteur. Il peut être nécessaire de faire une capture d'écran de l'image Maps au format PNG/JPG et d'ajouter des lignes pour ajuster l'orientation et mesurer l'angle avec précision.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png" width="300">

L'utilisation de Google Earth ou de ChatGPT est une autre alternative.

> [!NOTE]
>
> Solcast, dont le siège social se trouve à Sydney, en Australie (hémisphère sud), utilise une numérotation de l'azimut exprimée en degrés par rapport au nord. Si vous résidez dans l'hémisphère nord, il est probable que tout service de cartographie en ligne permettant de déterminer l'azimut utilise une convention de numérotation en degrés par rapport au *sud* , ce qui donnera des valeurs incompatibles.
>
> Une configuration Solcast avec un toit aligné Nord/Nord-Est/Nord-Ouest dans l'hémisphère nord ou Sud/Sud-Est/Sud-Ouest dans l'hémisphère sud est considérée comme potentiellement inhabituelle car ces orientations ne sont jamais directement face au soleil.
>
> Au démarrage, l'intégration vérifiera le réglage d'azimut de votre Solcast afin de détecter une éventuelle erreur de configuration. Si elle détecte un alignement de toit inhabituel, un message d'avertissement sera consigné dans le journal de Home Assistant et un problème sera signalé. Si vous recevez cet avertissement et que vous avez vérifié que vos paramètres Solcast sont corrects, vous pouvez simplement l'ignorer. Cet avertissement sert à détecter les erreurs de configuration.
>
> Il existe toujours des installations atypiques, comme deux toits orientés à l'ouest et à l'est avec des panneaux installés sur leurs deux faces, à 180 degrés l'une de l'autre. Un de ces toits sera considéré comme « inhabituel ». Vérifiez l'azimut selon Solcast et corrigez ou ignorez l'avertissement en conséquence. N'oubliez pas que 0° correspond au nord selon Solcast, les orientations étant relatives à cette direction.

## Installation

### HACS recommandé

*(Méthode d'installation recommandée)*

Installez-le comme dépôt par défaut à l'aide de HACS. Plus d'informations sur HACS sont disponibles [ici](https://hacs.xyz/) . Si vous ne l'avez pas encore installé, veuillez le faire dès maintenant !

La méthode la plus simple pour installer l'intégration est de cliquer sur le bouton ci-dessous pour ouvrir cette page dans votre page HACS de Home Assistant (il vous sera demandé de saisir l'URL de votre Home Assistant si vous n'avez jamais utilisé ce type de bouton auparavant).

[](https://my.home-assistant.io/redirect/hacs_repository/?owner=BJReplay&repository=ha-solcast-solar&category=integration)![Ouvrez votre instance Home Assistant et ouvrez un dépôt dans le Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)

Il vous sera demandé de confirmer que vous souhaitez ouvrir le dépôt dans HACS à l'intérieur de Home Assistant :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png">

Vous verrez cette page, avec un bouton `↓ Download` en bas à droite - cliquez dessus :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png">

Vous serez invité à télécharger le composant Solcast PV Forecast - cliquez sur `Download` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png">

Une fois l'application installée, vous verrez probablement apparaître une notification dans `Settings` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png">

Cliquez sur Paramètres, et vous devriez voir une notification de réparation indiquant qu'un `Restart required` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png">

Si vous ne voyez pas cette option (vous utilisez peut-être une ancienne version de Home Assistant), accédez à `System` , `Settings` , cliquez sur l'icône d'alimentation, puis `Restart Home Assistant` . Vous devez redémarrer Home Assistant avant de pouvoir configurer le composant personnalisé Solcast PV Forecast que vous venez de télécharger.

Une fois le redémarrage effectué, suivez les instructions de [la section Configuration](#configuration) pour poursuivre la configuration du composant d'intégration Solcast PV Forecast.

### Installation manuelle dans HACS

Plus d'infos [ici](https://hacs.xyz/docs/faq/custom_repositories/)

1. (Si vous l'utilisez, supprimez oziee/ha-solcast-solar dans HACS)
2. Ajoutez le dépôt personnalisé (menu à trois points verticaux, en haut à droite) `https://github.com/BJReplay/ha-solcast-solar` en tant `integration`
3. Recherchez « Solcast » dans HACS, ouvrez-le et cliquez sur le bouton `Download`
4. Voir [la configuration](#configuration) ci-dessous

Si vous utilisiez auparavant ha-solcast-solar d'Oziee, tout l'historique et la configuration devraient être conservés.

### Installation manuelle (sans utiliser HACS)

Vous **ne devriez probablement pas** procéder ainsi ! Utilisez la méthode HACS décrite ci-dessus, sauf si vous savez ce que vous faites et que vous avez une bonne raison de procéder à une installation manuelle.

1. À l'aide de l'outil de votre choix, ouvrez le dossier (répertoire) de votre configuration HA (où se trouve `configuration.yaml` ).
2. Si vous n'avez pas de dossier `custom_components` à cet emplacement, vous devez le créer.
3. Dans le dossier `custom_components` , créez un nouveau dossier nommé `solcast_solar`
4. Téléchargez *tous* les fichiers du dossier `custom_components/solcast_solar/` dans ce dépôt
5. Placez les fichiers téléchargés dans le nouveau dossier que vous avez créé.
6. *Redémarrez Home Assistant pour charger la nouvelle intégration.*
7. Voir [la configuration](#configuration) ci-dessous

### Versions bêta

Des versions bêta corrigeant les problèmes peuvent être disponibles.

Consultez https://github.com/BJReplay/ha-solcast-solar/releases pour vérifier si le problème a déjà été résolu. Si c'est le cas, activez l'entité `Solcast PV Pre-release` pour activer la mise à niveau bêta (ou, pour HACS v1, activez l'option `Show beta versions` lors du téléchargement »).

Vos commentaires suite aux tests des versions bêta sont les bienvenus dans les [discussions](https://github.com/BJReplay/ha-solcast-solar/discussions) du dépôt, où une discussion sera ouverte pour chaque version bêta active.

## Configuration

1. [Cliquez ici](https://my.home-assistant.io/redirect/config_flow_start/?domain=solcast_solar) pour ajouter directement une intégration `Solcast Solar` **ou**<br> a. Dans Home Assistant, accédez à Paramètres -&gt; [Intégrations](https://my.home-assistant.io/redirect/integrations/)<br> b. Cliquez sur `+ Add Integrations`

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png">

et commencez à taper `Solcast PV Forecast` pour faire apparaître l'intégration Solcast PV Forecast, puis sélectionnez-la.<br>

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png">

1. Saisissez votre `Solcast API Key` , `API limit` et votre option de mise à jour automatique, puis cliquez sur `Submit` . Si vous possédez plusieurs comptes Solcast (par exemple, plusieurs installations sur le toit), saisissez toutes les clés API de vos comptes Solcast, séparées par une virgule : `xxxxxxxx-xxxxx-xxxx,yyyyyyyy-yyyyy-yyyy` . ( *Remarque : Posséder plusieurs comptes Solcast peut enfreindre les conditions générales d'utilisation si les sites d'installation sont distants de moins d'un kilomètre (0,62 mile).) Votre limite d'API sera de 10 pour les nouveaux utilisateurs Solcast et de 50 pour les utilisateurs précoces. Si la limite d'API est identique pour plusieurs comptes, saisissez une seule valeur, ou les deux valeurs séparées par une virgule, ou encore* la limite d'API la plus basse parmi tous les comptes. Consultez la section [« Configuration des sites exclus »](#excluded-sites-configuration) pour plus d'informations sur l'utilisation de plusieurs clés API.
2. Si l'option de mise à jour automatique n'a pas été choisie, créez votre propre automatisation pour appeler l'action `solcast_solar.update_forecasts` aux moments où vous souhaitez mettre à jour les prévisions solaires.
3. Configurez les paramètres du tableau de bord Énergie de Home Assistant.
4. Pour modifier d'autres options de configuration après l'installation, sélectionnez l'intégration dans `Devices & Services` puis `CONFIGURE` .

Assurez-vous d'utiliser votre `API Key` et non l'identifiant de votre toit créé dans Solcast. Vous trouverez votre clé API ici : [clé API](https://toolkit.solcast.com.au/account) .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png" width="500">

> [!IMPORTANT] La clé API et les sites associés seront vérifiés lors de l'enregistrement de la configuration initiale. Il est possible que cette vérification initiale échoue si l'API Solcast est temporairement indisponible. Dans ce cas, veuillez réessayer la configuration après quelques minutes. Le message d'erreur de configuration vous indiquera si tel est le cas.

### Mise à jour des prévisions

Tous les sites doivent être mis à jour simultanément par l'intégration ; par conséquent, une limite de clé API différente utilisera la limite la plus basse de toutes les clés configurées.

> [!NOTE]
>
> L'utilisation de la méthode des moindres limites se justifie par sa simplicité, et toute solution de contournement s'avère problématique : les valeurs prévues pour chaque intervalle de trente minutes sont combinées pour former la prévision globale, ce qui implique que tous les sites doivent être représentés pour tous les intervalles. (Vous pourriez être tenté de penser qu'une « interpolation » des intervalles des autres sites serait envisageable, mais n'oubliez pas qu'il s'agit d'une prévision. Les demandes de fusion seront prises en compte, à condition d'être accompagnées de scénarios `pytest` complets.)

#### Mise à jour automatique des prévisions

Par défaut, pour les nouvelles installations, la mise à jour automatique des prévisions est activée.

L'activation de la mise à jour automatique permet de recevoir des prévisions actualisées réparties automatiquement sur les heures d'ensoleillement, ou sur une période de 24 heures. Le nombre de mises à jour quotidiennes est calculé en fonction du nombre de sites Solcast installés sur les toits et de la limite de l'API configurée, ou du nombre minimal de mises à jour possibles pour l'ensemble des sites en cas de clés API multiples.

S'il est nécessaire d'obtenir une mise à jour en dehors de ces heures, la limite de l'API dans la configuration d'intégration peut être réduite, puis une automatisation peut être mise en place pour appeler l'action `solcast_solar.force_update_forecasts` à l'heure souhaitée. (Notez que l'appel à l'action `solcast_solar.update_forecasts` sera refusé si la mise à jour automatique est activée ; utilisez alors la mise à jour forcée.)

Par exemple, pour effectuer une mise à jour juste après minuit et profiter de la mise à jour automatique, créez l'automatisation souhaitée pour forcer la mise à jour, puis réduisez en conséquence la limite d'appels API configurée dans cette automatisation. (Dans cet exemple, si la clé API autorise dix appels par jour et deux sites sur le toit, réduisez la limite à huit, car deux mises à jour seront utilisées lors de l'exécution de l'automatisation.)

L'utilisation de la mise à jour forcée n'incrémentera pas le compteur d'utilisation de l'API, ce qui est intentionnel.

> [!NOTE] *Transition vers la mise à jour automatique à partir de l'utilisation d'une automatisation :*
>
> Si vous utilisez actuellement l'automatisation recommandée, qui répartit les mises à jour de manière assez uniforme entre le lever et le coucher du soleil, l'activation de la mise à jour automatique du lever au coucher du soleil ne devrait pas entraîner d'échecs inattendus de récupération des prévisions dus à une saturation de l'API. L'automatisation recommandée n'est pas identique à la mise à jour automatique, mais son calendrier est très similaire.
>
> Si vous réduisez la limite de l'API et forcez une mise à jour supplémentaire à un autre moment de la journée (par exemple à minuit), un délai d'ajustement de 24 heures peut être nécessaire. Il est possible que des alertes de saturation de l'API soient signalées même si le nombre d'utilisations de l'API Solcast n'est pas atteint. Ces erreurs disparaîtront sous 24 heures.

#### Utilisation d'une automatisation HA pour mettre à jour les prévisions

Si la mise à jour automatique n'est pas activée, créez une ou plusieurs automatisations et configurez les intervalles de déclenchement souhaités pour interroger Solcast afin d'obtenir de nouvelles données de prévision. Utilisez l'action `solcast_solar.update_forecasts` . Des exemples sont fournis ; vous pouvez les modifier ou créer les vôtres en fonction de vos besoins.

<details><summary><i>Cliquez ici pour voir des exemples</i><p></p></summary>
</details>

Pour tirer le meilleur parti des appels API disponibles par jour, vous pouvez configurer l'automatisation pour qu'elle appelle l'API à un intervalle calculé en divisant le nombre d'heures de jour par le nombre total d'appels API que vous pouvez effectuer par jour.

Cette automatisation base les heures d'exécution sur le lever et le coucher du soleil, qui varient selon les régions du monde, répartissant ainsi la charge sur Solcast. Son fonctionnement est très similaire à la mise à jour automatique du lever au coucher du soleil, à la différence qu'elle intègre également un décalage horaire aléatoire, ce qui devrait permettre de réduire encore davantage le risque de saturation des serveurs Solcast par de nombreux appels simultanés.

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
> Si vous avez deux panneaux solaires sur votre toit, deux appels API seront effectués pour chaque mise à jour, ce qui réduit le nombre de mises à jour à cinq par jour. Dans ce cas, modifiez la valeur de : `api_request_limit = 5`

La prochaine automatisation comprend également une randomisation afin que les appels ne soient pas effectués exactement au même moment, ce qui devrait éviter que les serveurs Solcast ne soient submergés par plusieurs appels simultanés ; elle se déclenche toutes les quatre heures entre le lever et le coucher du soleil :

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

La prochaine automatisation se déclenchera à 4h, 10h et 16h, avec un délai aléatoire.

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
> Les serveurs Solcast semblent parfois être surchargés et renvoient alors des codes d'erreur 429 (Serveur trop occupé). L'intégration se met automatiquement en pause, puis tente de se reconnecter à plusieurs reprises. Cependant, il arrive que même cette méthode échoue à télécharger les données de prévision.
>
> Changer votre clé API n'est pas une solution, pas plus que désinstaller puis réinstaller l'intégration. Ces « astuces » peuvent sembler fonctionner, mais en réalité, vous avez simplement réessayé plus tard, et l'intégration a fonctionné car les serveurs Solcast étaient moins sollicités.
>
> Pour savoir si ce problème est à l'origine du vôtre, consultez les journaux de Home Assistant. Pour obtenir des informations détaillées (nécessaires pour signaler un problème), assurez-vous que la journalisation de débogage est activée.
>
> Les instructions pour la capture des journaux se trouvent dans le modèle de rapport de bogue ; vous les verrez si vous commencez à créer un nouveau problème. Assurez-vous d'inclure ces journaux si vous souhaitez obtenir l'aide des contributeurs du dépôt.
>
> Vous trouverez ci-dessous un exemple de message d'indisponibilité et de nouvelle tentative réussie (avec la journalisation de débogage activée). Dans ce cas, la nouvelle tentative réussit. Si dix tentatives consécutives échouent, la récupération des prévisions se terminera par une `ERROR` . Dans ce cas, déclenchez manuellement une autre action `solcast_solar.update_forecasts` (ou, si la mise à jour automatique est activée, utilisez `solcast_solar.force_update_forecasts` ), ou attendez la prochaine mise à jour planifiée.
>
> Si le chargement des données des sites au démarrage de l'intégration correspond à l'appel ayant échoué avec l'erreur 429 (Trop occupé), l'intégration démarrera si les sites ont été préalablement mis en cache et utilisera ces informations sans tenir compte du cache. Dans ce cas, les modifications apportées aux sites ne seront pas prises en compte et des résultats inattendus peuvent survenir. En cas de comportement inattendu, consultez le journal. Il est toujours conseillé de le consulter en cas d'anomalie ; un redémarrage permettra probablement de prendre en compte les sites mis à jour.

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

### Configurer les paramètres du tableau de bord énergétique HA

Accédez à `Settings` , `Dashboards` , `Energy` et cliquez sur l'icône en forme de crayon pour modifier la configuration de votre tableau de bord Énergie.

La prévision solaire doit être associée à un élément de production solaire dans votre tableau de bord Énergie.

Modifiez un élément `Solar production` `Solar Panels` ) que vous avez déjà créé (ou que vous allez créer). N'ajoutez pas un nouvel élément `Solar production` car cela risque de créer des dysfonctionnements.

Il ne peut y avoir qu'une seule configuration de la prévision totale Solcast PV dans le tableau de bord Énergie couvrant tous les sites (réseaux) de votre compte Solcast ; il n'est pas possible de diviser la prévision sur le tableau de bord Énergie pour différents champs solaires/sites Solcast.

> [!IMPORTANT] Si votre système ne comporte pas de capteur de production solaire, cette intégration ne fonctionnera pas dans le tableau de bord Énergie. Le graphique et l'ajout de l'intégration des prévisions nécessitent la présence d'un capteur de production solaire.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png" width="500">

Dans la section `Solar production forecast` , sélectionnez `Forecast Production` , puis l’option `Solcast Solar` . Cliquez sur `Save` , et Home Assistant se chargera du reste.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

## Interagir

L'intégration expose de nombreuses actions, capteurs et éléments de configuration, ainsi que de nombreux attributs de capteurs qui peuvent être activés.

Utilisez les `Developer tools` de Home Assistant pour examiner les attributs exposés, car leur nom dépend généralement du déploiement. Consultez les exemples fournis dans ce fichier README pour comprendre comment les utiliser.

Une collection de modèles Jinja2 est également disponible à l'adresse https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md, contenant des exemples de modèles de base, intermédiaires et avancés.

### Capteurs

Tous les noms de capteurs sont précédés du nom d'intégration `Solcast PV Forecast` .

Nom | Taper | Attributs | Unité | Description
--- | --- | --- | --- | ---
`Forecast Today` | nombre | Y | `kWh` | Prévisions totales de production solaire pour aujourd'hui.
`Forecast Tomorrow` | nombre | Y | `kWh` | Prévisions totales de production solaire pour le jour + 1 (demain).
`Forecast Day 3` | nombre | Y | `kWh` | Production solaire totale prévue pour le jour + 2 (jour 3, désactivé par défaut).
`Forecast Day 4` | nombre | Y | `kWh` | Production solaire totale prévue pour le jour + 3 (jour 4, désactivé par défaut).
`Forecast Day 5` | nombre | Y | `kWh` | Production solaire totale prévue pour le jour + 4 (jour 5, désactivé par défaut).
`Forecast Day 6` | nombre | Y | `kWh` | Production solaire totale prévue pour le jour + 5 (jour 6, désactivé par défaut).
`Forecast Day 7` | nombre | Y | `kWh` | Production solaire totale prévue pour le jour + 6 (jour 7, désactivé par défaut).
`Forecast This Hour` | nombre | Y | `Wh` | Production solaire prévue pour l'heure actuelle (les attributs contiennent une ventilation par site).
`Forecast Next Hour` | nombre | Y | `Wh` | Production solaire prévue pour l'heure suivante (les attributs contiennent une ventilation par site).
`Forecast Next X Hours` | nombre | Y | `Wh` | Prévision personnalisée de la production solaire pour les X prochaines heures, désactivée par défaut.<br> Remarque : Ces prévisions commencent à l'heure actuelle et ne sont pas alignées sur l'heure comme « Cette heure » ou « L'heure suivante ».
`Forecast Remaining Today` | nombre | Y | `kWh` | Production solaire restante prévue aujourd'hui.
`Peak Forecast Today` | nombre | Y | `W` | Production maximale prévue sur une période d'une heure aujourd'hui (les attributs contiennent une ventilation par site).
`Peak Time Today` | date/heure | Y |  | Heure de production solaire maximale prévue aujourd'hui (les attributs contiennent une ventilation par site).
`Peak Forecast Tomorrow` | nombre | Y | `W` | Production maximale prévue dans l'heure qui suit demain (les attributs contiennent une ventilation par site).
`Peak Time Tomorrow` | date/heure | Y |  | Heure de production solaire maximale prévue demain (les attributs contiennent une ventilation du site).
`Forecast Power Now` | nombre | Y | `W` | Puissance solaire nominale prévue à cet instant (les attributs contiennent une ventilation du site).
`Forecast Power in 30 Minutes` | nombre | Y | `W` | Puissance solaire nominale prévue en 30 minutes (les attributs contiennent une ventilation du site).
`Forecast Power in 1 Hour` | nombre | Y | `W` | Puissance solaire nominale prévue en 1 heure (les attributs contiennent une ventilation du site).

> [!NOTE]
>
> Lorsqu'une ventilation du site est disponible en tant qu'attribut, le nom de l'attribut est l'identifiant de ressource du site Solcast (les tirets étant remplacés par des traits de soulignement).
>
> La plupart des capteurs incluent également un attribut pour `estimate` , `estimate10` et `estimate90` . Des capteurs modèles peuvent être créés pour exposer leur valeur, ou la `state_attr()` peut être utilisée directement dans les automatisations.
>
> Accédez-y dans un capteur modèle ou une automatisation en utilisant par exemple :
>
> ```
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', '1234_5678_9012_3456') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10_1234_5678_9012_3456') | float(0) }}
> ```
>
> Voir également l'exemple de graphique PV ci-dessous pour savoir comment représenter graphiquement les détails des prévisions à partir de l'attribut detailedForecast.

> [!NOTE]
>
> Les valeurs de `Next Hour` et `Forecast Next X Hours` peuvent différer si le paramètre personnalisé « X heures » est égal à 1. Cela s’explique simplement.
>
> Ces calculs sont effectués à partir d'heures de début et de fin différentes. L'un se base sur le début de l'heure actuelle, c'est-à-dire sur une période antérieure, par exemple de 14h00 à 15h00. L'autre, basé sur un capteur personnalisé, se base sur l'heure actuelle par intervalles de cinq minutes, par exemple de 14h20 à 15h20, en utilisant des valeurs interpolées.
>
> Le résultat sera probablement différent selon le moment où la valeur est demandée ; ce n'est donc pas faux, c'est simplement différent.

### Attributs

Comme indiqué précédemment, les attributs des capteurs permettent d'utiliser les variations d'état des capteurs dans les modèles. On peut citer comme exemples la confiance de l'estimation, `estimate10` , `estimate` `estimate90` . L' *état* du capteur est généralement laissé à sa valeur par défaut « `estimate` , mais il peut être souhaitable d'afficher le 10e percentile d'un capteur sur un tableau de bord ; cette fonctionnalité est assurée par l'utilisation des valeurs *d'attributs* .

Certains noms d'attributs sont spécifiques au déploiement (des exemples sont fournis ici), et certains attributs sont désactivés par défaut ou selon les préférences de l'utilisateur afin de simplifier l'interface. Ces préférences sont définies dans la boîte de dialogue `CONFIGURE` .

Les noms d'attributs ne doivent pas contenir de tiret. Les identifiants de ressources de site Solcast *utilisent* un tiret ; par conséquent, lorsqu'un attribut porte le nom de l'identifiant de ressource de site qu'il représente, les tirets sont remplacés par des traits de soulignement.

Tous les capteurs de prévision détaillés qui fournissent des ventilations horaires ou semi-horaires fournissent (comme les données Solcast sous-jacentes) des données en kW - ce sont des capteurs de puissance, et non des capteurs d'énergie, et ils représentent la prévision de puissance moyenne pour la période.

Pour tous les capteurs :

- `estimate10` : valeur prévisionnelle du 10e percentile (nombre)
- `estimate` : valeur prévisionnelle du 50e percentile (nombre)
- `estimate90` : valeur prévisionnelle du 90e percentile (nombre)
- `1234_5678_9012_3456` : Valeur d'un site individuel, c'est-à-dire une partie du total (nombre)
- `estimate10_1234_5678_9012_3456` : 10e pour une valeur de site individuelle (nombre)
- `estimate_1234_5678_9012_3456` : 50e pour une valeur de site individuelle (nombre)
- `estimate90_1234_5678_9012_3456` : 90e pour une valeur de site individuelle (nombre)

Pour le capteur `Forecast Next X Hours` uniquement :

- `custom_hours` : Le nombre d'heures signalées par le capteur (nombre)

Pour les capteurs de prévision journalière uniquement :

- `detailedForecast` : Ventilation par demi-heure de la production d’énergie moyenne attendue pour chaque intervalle (liste des données, unités en kW et non en kWh). Si l’amortissement automatique est actif, le facteur déterminé pour chaque intervalle est également inclus.
- `detailedHourly` : Ventilation horaire de la production d'énergie moyenne prévue pour chaque intervalle (liste de dictionnaires, unités en kW)
- `detailedForecast_1234_5678_9012_3456` : Une ventilation semi-horaire spécifique au site de la production d'énergie moyenne attendue pour chaque intervalle (liste de dictionnaires, unités en kW)
- `detailedHourly_1234_5678_9012_3456` : Une ventilation horaire spécifique au site de la production d'énergie moyenne attendue pour chaque intervalle (liste de dictionnaires, unités en kW)

La « liste de dictionnaires » a le format suivant, avec des exemples de valeurs utilisées : (Notez l’incohérence entre `pv_estimateXX` et `estimateXX` utilisé ailleurs. C’est dû à l’historique.)

JSON :

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

YAML :

```yaml
- period_start: '2025-04-06T08:00:00+10:00'
  dampening_factor: 0.888, <== for detailedForecast only, and only if automated dampening is enabled
  pv_estimate10: 10.000
  pv_estimate: 50.000
  pv_estimate90: 90.000
- ...
```

### Actes

Action | Description
--- | ---
`solcast_solar.update_forecasts` | Mettre à jour les données prévisionnelles (refusé si la mise à jour automatique est activée).
`solcast_solar.force_update_forecasts` | Forcer la mise à jour des données prévisionnelles (effectue une mise à jour indépendamment du suivi de l'utilisation de l'API ou du paramètre de mise à jour automatique, et n'incrémente pas le compteur d'utilisation de l'API ; refusée si la mise à jour automatique n'est pas activée).
`solcast_solar.force_update_estimates` | Forcer la mise à jour des données réelles estimées (n'incrémente pas le compteur d'utilisation de l'API, refusée si l'obtention des données réelles estimées n'est pas activée).
`solcast_solar.clear_all_solcast_data` | Supprime les données mises en cache et lance une récupération immédiate des nouvelles valeurs passées réelles et prévisionnelles.
`solcast_solar.query_forecast_data` | Renvoie une liste de données prévisionnelles utilisant une plage de dates et d'heures de début et de fin.
`solcast_solar.query_estimate_data` | Renvoie une liste de données réelles estimées en utilisant une plage de dates et d'heures de début et de fin.
`solcast_solar.set_dampening` | Mettre à jour les facteurs d'amortissement.
`solcast_solar.get_dampening` | Obtenez les facteurs d'amortissement actuellement définis.
`solcast_solar.set_hard_limit` | Définir une limite stricte de prévision de l'onduleur.
`solcast_solar.remove_hard_limit` | Supprimer la limite stricte de prévision de l'onduleur.

Des exemples de paramètres sont fournis ici pour chaque `query` , `set` et action `get` . Utilisez `Developer tools` | `Actions` pour afficher les paramètres disponibles pour chaque action, accompagnés d'une description.

Lorsqu'un paramètre « site » est nécessaire, utilisez l'ID de ressource du site Solcast et non le nom du site.

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

### Configuration

Nom | Taper | Description
--- | --- | ---
`Forecast Field` | sélecteur | Sélectionnez le niveau de confiance des prévisions utilisé pour les états des capteurs : « estimation », « estimation10 » ou « estimation90 ».

### Diagnostique

Tous les noms des capteurs de diagnostic sont précédés de `Solcast PV Forecast` à l'exception du `Rooftop site name` .

Nom | Taper | Attributs | Unité | Description
--- | --- | --- | --- | ---
`API Last Polled` | date/heure | Y | `datetime` | Date et heure de la dernière mise à jour réussie des prévisions.
`API Limit` | nombre | N | `integer` | Nombre total de fois où l'API peut être appelée sur une période de 24 heures[^1].
`API used` | nombre | N | `integer` | Nombre total de fois où l'API a été appelée aujourd'hui (le compteur d'API est remis à zéro à minuit UTC)[^1].
`Dampening` | booléen | Y | `bool` | Indique si l'amortissement est activé (désactivé par défaut).
`Hard Limit Set` | nombre | N | `float` ou `bool` | `False` si non défini, sinon valeur en `kilowatts` .
`Hard Limit Set ******AaBbCc` | nombre | N | `float` | Limite maximale de consommation par compte individuel. Valeur en `kilowatts` .
`Rooftop site name` | nombre | Y | `kWh` | Prévisions totales pour les toitures aujourd'hui (les attributs contiennent la configuration du site)[^2].

Les attributs `API Last Polled` incluent les éléments suivants :

- `failure_count_today` : Le nombre d'échecs (comme `429/Too busy` ) qui se sont produits depuis minuit, heure locale.
- `failure_count_7_day` : Le nombre de défaillances survenues au cours des sept derniers jours.
- `last_attempt` : Date et heure de la dernière tentative de mise à jour des prévisions. « Actuellement en bonne santé » signifie que la dernière interrogation a eu lieu au moins une fois avant la dernière tentative.

Si la mise à jour automatique est activée, la dernière interrogation inclut également les attributs suivants :

- `auto_update_divisions` : Le nombre de mises à jour automatiques configurées pour chaque jour.
- `auto_update_queue` : Un maximum de 48 mises à jour automatiques futures sont actuellement en attente.
- `next_auto_update` : Date et heure de la prochaine mise à jour automatique programmée.

Si l'amortissement est actif, le capteur d'amortissement présente également les attributs suivants :

- `integration_automated` : Booléen. Indique si l'amortissement automatisé est activé.
- `last_updated` : Datetime. Date et heure de la dernière modification des facteurs d'amortissement.
- `factors` : Dict. L' `interval` de début heure:minute, et `factor` sous forme de nombre à virgule flottante.

Exemple d'attributs de capteur d'amortissement :

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

Les attributs `Rooftop site name` comprennent :

- `azimuth` / `tilt` : Orientation du panneau.
- `capacity` : Capacité du site en puissance CA.
- `capacity_dc` : Capacité du site en puissance CC.
- `install_date` : Date d'installation configurée.
- `loss_factor` : "facteur de perte" configuré.
- `name` : Le nom du site configuré sur solcast.com.
- `resource_id` : L'identifiant de la ressource du site.
- `tags` : Les étiquettes définies pour le site sur le toit.

> [!NOTE]
>
> La latitude et la longitude ne sont pas incluses intentionnellement dans les attributs du site sur le toit pour des raisons de confidentialité.

[^1] : Les informations d'utilisation de l'API sont suivies en interne et peuvent ne pas correspondre à l'utilisation réelle du compte.

[^2] : Chaque toit créé dans Solcast sera listé séparément.

## Configuration avancée

### Configuration d'amortissement

Les valeurs d'amortissement tiennent compte de l'ombrage et ajustent la production prévue. L'amortissement peut être déterminé automatiquement ou en dehors du système d'intégration et défini par une action de service.

Toute modification des facteurs d'amortissement sera appliquée aux prévisions futures (y compris celle du jour même). L'historique des prévisions conservera l'amortissement en vigueur au moment de sa modification.

L'amortissement automatique (décrit ci-dessous) calcule les facteurs d'amortissement globaux pour l'ensemble des toitures. Si un amortissement par toiture est souhaité, il est possible de le modéliser séparément avec votre propre solution d'amortissement, puis de définir les facteurs à l'aide de l'action ` `solcast_solar.set_dampening` . Voir la section [« Amortissement granulaire »](#granular-dampening) ci-dessous.

> [!NOTE]
>
> Lorsque l'amortissement automatique est activé, il ne sera pas possible de définir les facteurs d'amortissement par action de service, ni manuellement dans les options d'intégration, ni en écrivant dans le fichier `solcast-dampening.json` .
>
> (Si la méthode d'écriture du fichier d'amortissement est tentée, le contenu du nouveau fichier sera ignoré, puis écrasé ultérieurement par les facteurs d'amortissement automatisés mis à jour lors de leur modélisation.)

#### Amortissement automatisé

L'intégration comprend notamment un système d'amortissement automatique : l'historique de production réel est comparé aux estimations de production passée afin de détecter les anomalies de production régulières. Ceci permet d'identifier les périodes d'ombrage probable des panneaux et d'appliquer automatiquement un facteur d'amortissement aux périodes de la journée susceptibles d'être affectées par l'ombrage, réduisant ainsi la production d'énergie prévue.

L'amortissement automatique est dynamique et utilise jusqu'à quatorze jours de données de production et d'estimations de production glissantes pour construire son modèle et déterminer les facteurs d'amortissement à appliquer. Quatorze jours maximum sont utilisés. Lors de l'activation de cette fonctionnalité, toute limite d'historique peut entraîner une réduction des données disponibles, mais celles-ci atteindront quatorze jours ultérieurement, améliorant ainsi la modélisation.

L'amortissement automatisé appliquera les mêmes facteurs d'amortissement à tous les sites de toiture, en fonction de la génération totale de localisation et des données Solcast.

> [!NOTE]
>
> L'amortissement automatisé peut ne pas vous convenir, notamment en raison de la manière dont vos producteurs d'énergie déclarent leur consommation, ou si vous bénéficiez d'un contrat sur le marché de gros de l'énergie où les prix peuvent devenir négatifs, ce qui vous oblige à limiter l'injection d'énergie sur votre site dans ces moments-là. (Vous trouverez ci-dessous une solution envisageable à ce problème.)
>
> Cette fonction d'amortissement automatique intégrée conviendra à beaucoup de gens, mais ce n'est pas une solution miracle.
>
> Cela peut sembler être une simple option à cocher dans la configuration, mais il n'en est rien. Il s'agit d'un code complexe qui gère différents types de rapports de production photovoltaïque et d'éventuels problèmes de communication entre votre onduleur et Home Assistant, tout en détectant les productions anormales dues à l'ombrage.
>
> Si vous pensez que l'amortissement automatique ne fonctionne pas correctement, veuillez réfléchir, mener des investigations, puis signaler tout problème d'amortissement automatique, dans cet ordre. Veuillez inclure dans votre rapport de problème les détails expliquant pourquoi vous pensez que l'amortissement automatique ne fonctionne pas et la solution envisagée.
>
> Si, après investigation, vous constatez qu'un problème provient de votre générateur artisanal, l'amortissement automatique n'est peut-être pas la solution idéale. Dans ce cas, nous vous recommandons de concevoir votre propre système d'amortissement ou de formuler des suggestions d'amélioration constructives sur le plan technique. Vous pouvez utiliser les composants nécessaires pour construire votre propre système d'amortissement granulaire.
>
> N'hésitez pas à consulter également les « options avancées » d'intégration. De nombreux paramètres techniques permettent de configurer l'amortissement automatique et pourraient résoudre votre problème.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png" width="500">

Le principe de fonctionnement est simple, reposant sur deux entrées principales et une troisième optionnelle.

##### Théorie de fonctionnement

L'atténuation automatique commence par établir un ensemble optimal et cohérent [d'estimations de la production réelle](https://github.com/BJReplay/ha-solcast-solar/issues/373#key-input-estimated-actual-data-from-solcast) (plusieurs périodes d'une demi-heure) sur les quatorze derniers jours. (Il ne s'agit pas de la production réelle du site, mais d'une estimation optimale de Solcast quant à la production attendue).

Le système compare ensuite ces données à [l'historique de production](#key-input-actual-pv-generation-for-your-site) pour ces périodes (à l'exclusion des périodes où les limites d'exportation ont pu être atteintes par [une limitation optionnelle](#optional-input-site-export-to-the-grid-combined-with-a-limit-value) ou lorsqu'elles ont été intentionnellement réduites). La valeur de production réelle la plus élevée est sélectionnée parmi les périodes similaires présentant les meilleures estimations, mais uniquement s'il existe plusieurs valeurs de production. Cette valeur détermine si des facteurs externes sont susceptibles d'influencer la production et sert à calculer un facteur d'amortissement de base.

Le système d'amortissement automatique, qui détecte les périodes d'ombrage affectant la production solaire, exclut les intervalles de temps où la production photovoltaïque est sous-estimée (jours où elle est réduite par la couverture nuageuse, la pluie, etc.).

En d'autres termes, et en langage très simple, Solcast a estimé par le passé que la production moyenne aurait dû être de « X » kW à une certaine heure par temps ensoleillé, mais le maximum atteint récemment n'a été que de « Y » kW. L'intégration ajustera donc les prévisions futures vers « Y ». Plus simplement encore, la production réelle estimée est systématiquement supérieure à la production théorique, d'où la réduction des prévisions.

Comme les périodes de prévision varient par rapport aux meilleures estimations en raison de la couverture nuageuse, le facteur de base est ajusté avant d'être appliqué aux prévisions au moyen d'un calcul de différence logarithmique. Si la production solaire prévue s'écarte sensiblement de la production solaire estimée ayant servi à déterminer le facteur d'amortissement de base, ce dernier est ajusté afin de minimiser son impact (c'est-à-dire ramené plus près de 1,0). Cet ajustement est effectué pour chaque intervalle de prévision ; par conséquent, des facteurs différents seront probablement appliqués chaque jour.

L'ajustement du facteur d'amortissement de base est effectué car une variation significative des prévisions de production pour une période donnée, par rapport aux périodes précédentes plus favorables, indique une période de forte nébulosité. Cet ajustement permet d'adapter l'amortissement aux périodes nuageuses, où la lumière diffuse, et non la lumière directe du soleil (la composante la plus affectée par l'ombrage), constitue la principale source de production solaire.

> [!TIP]
>
> Consultez l'attribut `detailedForecast` de chaque prévision journalière pour voir les facteurs d'amortissement automatiques appliqués à chaque intervalle. Un exemple de graphique Apex est inclus dans [`TEMPLATES.md`](https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md) pour illustrer une application pratique de ces informations d'amortissement.

##### Données clés : Estimation des données réelles de Solcast

Outre les prévisions, le service Solcast estime également la production réelle probable de chaque toiture durant la journée, en se basant sur l'imagerie satellite haute résolution, les observations météorologiques et la qualité de l'air (présence de vapeurs d'eau et de smog). Ces données, appelées « estimations de la production réelle », sont généralement assez précises pour un emplacement donné.

L'obtention de données estimées nécessite un appel API, lequel consommera le quota API d'un utilisateur occasionnel. Il est donc important de prendre en compte cette consommation d'appels API lorsque vous activez la limitation automatique, sachant qu'un appel est utilisé par site Solcast configuré sur le toit, par jour et par clé API. (Réduisez la limite d'appels API pour les mises à jour des prévisions de un pour un seul site sur le toit, ou de deux pour deux sites.)

Les données réelles estimées sont acquises chaque jour juste après minuit, heure locale, et mises à jour aléatoirement toutes les 15 minutes. Lorsque l'amortissement automatique est activé, de nouveaux facteurs d'amortissement pour le lendemain sont modélisés immédiatement après la mise à jour des données réelles estimées. Il est également possible de forcer une mise à jour des données réelles estimées ; le cas échéant, des facteurs d'amortissement seront également modélisés.

> [!TIP]
>
> Si votre objectif est d'obtenir le plus grand nombre possible de mises à jour de prévisions au cours de la journée, l'utilisation d'estimations des valeurs réelles et d'un amortissement automatique n'est pas adaptée. Cela réduira le nombre de mises à jour de prévisions possibles.

##### Information clé : Production photovoltaïque réelle de votre site

La production est calculée à partir des données historiques d'un ou plusieurs capteurs. Une installation photovoltaïque avec onduleur unique est généralement équipée d'un capteur de « production photovoltaïque croissante » qui fournit une valeur de « production photovoltaïque » ou d'« exportation photovoltaïque » (c'est-à-dire l'énergie produite par le soleil sur votre toit, et *non* injectée dans le réseau). Plusieurs onduleurs possèdent chacun une valeur, et les données de tous les capteurs peuvent être collectées ; elles sont ensuite totalisées pour l'ensemble des toitures.

Un ou plusieurs capteurs d'énergie à consommation croissante doivent être fournis. Ces capteurs peuvent se réinitialiser à minuit ou être de type « à consommation croissante continue » ; l'important est qu'ils augmentent tout au long de la journée.

L'intégration détermine les unités en analysant l'attribut `unit_of_measurement` et s'ajuste en conséquence. Si cet attribut n'est pas défini, les valeurs sont considérées comme étant en kWh. L'historique de production est mis à jour à minuit, heure locale.

> [!TIP]
>
> Pour que l'intégration puisse détecter une production photovoltaïque anormale, les unités de production doivent transmettre régulièrement leurs données à Home Assistant. Seules les unités transmettant périodiquement leur dernière valeur de production ou dont la production augmente régulièrement sont prises en charge. Si votre unité de production photovoltaïque ne présente pas un profil de production similaire, l'amortissement automatique risque de ne pas fonctionner.

> [!NOTE]
>
> N’incluez pas les entités de génération pour les toitures « éloignées » qui ont été explicitement exclues du total des capteurs. L’amortissement automatique ne fonctionne pas pour les toitures exclues.

##### Entrée facultative : exportation du site vers la grille, combinée à une valeur limite

Lorsque l'excédent d'électricité produit localement est injecté dans le réseau, la quantité d'énergie exportée est généralement limitée. Le système intégré surveille ces exportations et, en cas de limitation des exportations (atteinte de la limite pendant cinq minutes ou plus), la période de production correspondante est exclue par défaut du calcul de la marge de sécurité pour *tous* les jours concernés. Ce mécanisme permet de distinguer les limitations dues à l'ombrage d'un arbre ou d'une cheminée, ainsi que les limitations artificielles liées au site.

L'exportation vers la grille a généralement lieu en milieu de journée, une période rarement affectée par l'ombrage.

Un seul capteur d'énergie incrémentale est autorisé et sa valeur peut être remise à zéro à minuit. La limite d'exportation optionnelle ne peut être spécifiée qu'en kW. Consultez la section des options avancées pour connaître les possibilités de modification de ce comportement d'exclusion « tous les jours ».

> [!TIP]
>
> Il est possible que la valeur limite d'exportation mesurée par certains composants d'un système photovoltaïque ne corresponde pas exactement à la limite réelle. Cela peut prêter à confusion, mais cela est dû aux variations des circuits de mesure des pinces ampèremétriques.
>
> Exemple : avec une limite d’exportation de 5,0 kW, une passerelle Enphase peut mesurer précisément 5,0 kW, tandis qu’une passerelle de batterie Tesla installée dans le même système peut mesurer une puissance de 5,3 kW. Si la valeur du capteur utilisée pour l’amortissement automatique provient de la passerelle Tesla, assurez-vous que la limite d’exportation spécifiée est bien de 5,3 kW.

##### Activation initiale

Pour que l'amortissement automatique fonctionne, il doit avoir accès à un ensemble minimal de données. L'historique de génération est immédiatement chargé à partir de l'historique du ou des capteurs, mais l'historique réel estimé par Solcast ne sera reçu qu'après minuit, heure locale. De ce fait, lors de sa première activation, la fonction ne modélisera presque certainement aucun facteur d'amortissement immédiatement.

(S'il s'agit d'une nouvelle installation où les valeurs réelles estimées sont obtenues une seule fois, les facteurs peuvent être modélisés immédiatement.)

> [!TIP]
>
> La plupart des messages d'amortissement automatisés sont consignés au niveau `DEBUG` . Cependant, les messages indiquant que les facteurs d'amortissement ne peuvent pas encore être modélisés (et la raison de cette impossibilité) sont consignés au niveau `INFO` . Si votre niveau de journalisation minimal pour l'intégration est `WARNING` ou supérieur, vous ne verrez pas ces notifications.

##### Modification du comportement d'amortissement automatisé

L'amortissement automatique conviendra à de nombreuses personnes, mais il existe des situations où, tel qu'il est implémenté, il ne sera pas adapté. Dans ces cas, les utilisateurs avancés pourront souhaiter modifier son comportement.

Le principe fondamental de l'amortissement automatique repose sur la fiabilité des mesures de production photovoltaïque par rapport à la production réelle estimée. Si ces mesures ne sont pas fiables, en raison d'une limitation artificielle, l'amortissement automatique doit en être informé. Dans le cas d'une simple limitation des injections d'électricité par le réseau à une valeur fixe, cette fonctionnalité est intégrée et facile à mettre en œuvre. En revanche, il est possible de signaler une production photovoltaïque instable sur un intervalle donné, en fonction de circonstances plus complexes.

C’est là que vous pouvez faire preuve de créativité avec un capteur à modèle nommé spécifiquement pour que les intervalles de production PV soient ignorés lorsqu’on ne peut pas se fier à leur précision (c’est-à-dire pas en production « à pleine capacité »).

Par exemple, il peut arriver que l'on ne puisse pas injecter d'électricité sur le réseau, ou que l'on choisisse de ne pas le faire. Dans ces cas-là, la consommation des ménages égalera la production, ce qui perturbera le système de régulation automatique.

Pour modifier le comportement de l'amortissement automatique, une entité modèle peut être créée sous le nom `solcast_suppress_auto_dampening` . Celle-ci peut utiliser la plateforme « sensor », « binary_sensor » ou « switch ».

L'intégration surveillera les changements d'état de cette entité. Si son état est « activé », « 1 », « vrai » ou « Vrai » à *un instant donné d'un intervalle de production photovoltaïque d'une demi-heure,* le système d'amortissement automatique modifiera son comportement et exclura cet intervalle. En revanche, si l'état de l'entité est « désactivé », « 0 », « faux » ou « Faux » pendant *toute la durée de l'intervalle* , ce dernier sera inclus normalement dans l'amortissement automatique.

La suppression est également complémentaire à celle assurée par la détection des limites d'exportation du site ; il convient donc probablement de supprimer ces aspects de configuration ou de les examiner attentivement.

Il lui faut également un historique des changements d'état pour être compréhensible ; sa mise en place prendra donc du temps. Il vous faudra faire preuve de bon sens et de patience pour utiliser cette fonctionnalité.

> [!TIP]
>
> Définissez également l'option avancée `automated_dampening_no_limiting_consistency` sur `true` si nécessaire.
>
> Par défaut, si une limitation est détectée pour un intervalle quelconque un jour donné, cet intervalle sera ignoré pour tous les jours des quatorze derniers jours, sauf si cette option est activée.

Voici une séquence de mise en œuvre probable :

1. Créez l'entité modèle `solcast_suppress_auto_dampening` .
2. Désactivez l'amortissement automatique car il sera dysfonctionnel et source de confusion (mais il l'était déjà auparavant car vous ne pouvez pas exporter ou choisissez de ne pas le faire en raison d'un prix de gros négatif).
3. Supprimez votre fichier `/config/solcast_solar/solcast-generation.json` . Son historique risque de fausser les résultats de l'amortissement automatique.
4. Assurez-vous que l'enregistreur est configuré avec `purge_keep_days` d'au moins sept jours. Lorsque l'atténuation automatique est activée, il tentera de charger jusqu'à sept jours d'historique de production (une option avancée permet d'en obtenir davantage). Laissez-le faire le moment venu. Si vous purgez habituellement plus fréquemment, vous pouvez toujours rétablir la valeur initiale au bout d'une semaine. (Il n'est pas nécessaire de désactiver l'acquisition des valeurs réelles estimées.)
5. Définissez l'option avancée `automated_dampening_no_limiting_consistency` sur `true` si nécessaire.
6. Redémarrez complètement HA pour activer le paramètre d'enregistrement et permettre à l'intégration Solcast de comprendre que les données de génération sont désormais manquantes.
7. Attendez patiemment une semaine pour permettre à la nouvelle entité de se constituer un historique.
8. Activez l'amortissement automatique et observez-le agir sur votre entité d'adaptation.

L'activation de la journalisation au niveau `DEBUG` pour l'intégration permettra de visualiser ce qui se passe ; c'est une mesure judicieuse à prendre lors de la configuration. Si vous avez besoin d'aide, il sera *essentiel* d'avoir les journaux à portée de main et de les partager.

##### Notes d'atténuation automatisées

Un facteur modélisé supérieur à 0,95 est considéré comme non significatif et est ignoré. Vos commentaires sur l'opportunité de prendre en compte et d'exploiter ces faibles facteurs sont les bienvenus.

Ces petits facteurs seraient corrigés en fonction des prévisions de production ; il serait donc judicieux de ne pas les négliger. Cependant, un écart faible et régulier par rapport aux prévisions est probablement dû à une mauvaise configuration du site sur le toit ou à une variation saisonnière, et non à l’ombrage.

L'objectif de l'amortissement automatique n'est pas de corriger les erreurs de configuration des installations Solcast sur les toits, ni les particularités de production liées au type de panneau, ni d'améliorer les prévisions. Il s'agit de détecter les écarts de production réels par rapport aux prévisions, dus à des facteurs locaux.

> [!TIP]
>
> Si vous disposez de deux semaines de données historiques et que des facteurs d'amortissement sont générés toutes les demi-heures lorsque le soleil brille, il est presque certain qu'il y a un problème de configuration. La production ne correspond jamais à la production réelle estimée et il est probable que la configuration de votre installation Solcast sur le toit soit incorrecte.

Toute erreur de configuration du site d'analyse d'énergie en toiture peut avoir un impact significatif sur les prévisions, mais il convient de la corriger dans la configuration du site. Il est fortement recommandé de vérifier que la configuration est correcte et que les prévisions sont raisonnablement précises les jours de bonne production avant de configurer l'amortissement automatique. Autrement dit, si des prévisions douteuses apparaissent, désactivez l'amortissement automatique avant d'en diagnostiquer la cause.

Les ajustements effectués par l'amortissement automatisé peuvent entraver les efforts visant à résoudre les problèmes de configuration de base, et s'il est activé, le signalement d'un problème d'écart par rapport aux prévisions où l'amortissement automatisé n'est pas impliqué risque d'entraver la résolution du problème.

Nous ne voulons pas cela.

Les capteurs d'énergie externes (comme les panneaux photovoltaïques et les panneaux solaires) doivent avoir une unité de mesure de mWh, Wh, kWh ou MWh et afficher une augmentation cumulative tout au long de la journée. Si l'unité de mesure ne peut être déterminée, le kWh est utilisé par défaut. Les autres unités, comme le GWh ou le TWh, ne sont pas adaptées à un usage résidentiel et entraîneraient une perte de précision inacceptable lors de la conversion en kWh ; elles ne sont donc pas prises en charge. Les autres unités d'énergie, comme le joule et la calorie, ne sont pas non plus prises en charge, car elles sont rarement utilisées pour l'électricité.

##### Retour

Vos commentaires concernant votre expérience avec la fonction d'amortissement automatique seront les bienvenus dans les discussions sur le référentiel d'intégration.

La journalisation complète au niveau `DEBUG` a lieu lorsque l'atténuation automatique est activée, et vous êtes encouragé à examiner et à inclure ces détails consignés dans toute discussion susceptible de mettre en évidence une lacune, une expérience (positive ou négative !) ou une opportunité d'amélioration.

#### simple amortissement horaire

Vous pouvez modifier le facteur d'atténuation pour chaque heure. Les valeurs valides sont comprises entre 0,0 et 1,0. Une valeur de 0,95 atténuera (réduira) chaque valeur de prévision Solcast de 5 %. Cette modification est visible dans les valeurs et attributs des capteurs, ainsi que dans le tableau de bord Énergie de Home Assistant.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png" width="500">

> [!TIP]
>
> La plupart des utilisateurs de la configuration d'amortissement ne saisissent pas directement les valeurs dans les paramètres de configuration. Ils créent plutôt des automatisations pour définir des valeurs adaptées à leur emplacement selon les jours ou les saisons, et ces automatisations appellent l'action `solcast_solar.set_dampening` .
>
> Les facteurs justifiant un amortissement approprié peuvent être les suivants : différents degrés d’ombrage peuvent survenir au début ou à la fin de la journée selon les saisons, lorsque le soleil est proche de l’horizon et peut projeter une longue ombre sur les bâtiments ou les arbres environnants.

#### Amortissement granulaire

Il est possible de paramétrer l'atténuation pour chaque site Solcast ou par intervalles d'une demi-heure. Cela nécessite l'utilisation de l'action `solcast_solar.set_dampening` ou la création/modification d'un fichier nommé `solcast-dampening.json` dans le dossier de configuration de Home Assistant.

Cette action accepte une chaîne de facteurs d'amortissement, ainsi qu'un identifiant de site optionnel. (Le site peut être spécifié à l'aide de tirets ou de traits de soulignement.) Pour un amortissement horaire, indiquez 24 valeurs. Pour un amortissement semi-horaire, 48 valeurs. L'appel de cette action crée ou met à jour le fichier `solcast-dampening.json` lorsqu'un site ou 48 valeurs de facteurs sont spécifiés. Si vous définissez un amortissement global avec 48 facteurs, un site « all » optionnel peut être spécifié (ou simplement omis dans ce cas).

```yaml
action: solcast_solar.set_dampening
data:
  damp_factor: 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
  #site: 1234-5678-9012-3456
```

Si aucun ID de ressource de site n'est spécifié et que 24 valeurs d'amortissement sont fournies, l'amortissement granulaire sera supprimé et l'amortissement horaire global configuré s'appliquera à tous les sites. (L'amortissement granulaire peut également être désactivé via la boîte de dialogue `CONFIGURE` de l'intégration.)

Il n'est pas nécessaire de déclencher l'action. Le fichier peut être mis à jour directement et, s'il est créé ou modifié, il sera lu et utilisé. Les opérations de création, de mise à jour et de suppression de ce fichier sont surveillées, et les modifications apportées aux prévisions seront visibles en moins d'une seconde après l'opération.

Si un amortissement granulaire est configuré pour un seul site au sein d'une configuration multisite, cet amortissement ne s'appliquera qu'aux prévisions de ce site. Les autres sites ne seront pas concernés.

L'amortissement de chaque site peut bien sûr être défini, et dans ce cas, tous les sites doivent spécifier le même nombre de valeurs d'amortissement, soit 24, soit 48.

<details><summary><i>Cliquez pour voir des exemples de fichiers d'amortissement</i></summary>
</details>

Les exemples suivants peuvent servir de point de départ pour la configuration de l'atténuation granulaire par fichier. Veillez à utiliser vos propres identifiants de ressources de site plutôt que ceux des exemples. Le fichier doit être enregistré dans le dossier de configuration de Home Assistant et nommé `solcast-dampening.json` .

Exemple d'amortissement horaire pour deux sites :

```yaml
{
  "1111-aaaa-bbbb-2222": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "cccc-4444-5555-dddd": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Exemple d'amortissement horaire pour un site unique :

```yaml
{
  "eeee-6666-7777-ffff": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Exemple d'atténuation par demi-heure pour deux sites :

```yaml
{
  "8888-gggg-hhhh-9999": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "0000-iiii-jjjj-1111": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Exemple d'atténuation par demi-heure pour tous les sites :

```yaml
{
  "all": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```




#### Lecture des valeurs prévisionnelles dans un système automatisé

L'action `solcast_solar.query_forecast_data` peut renvoyer des prévisions atténuées et non atténuées (incluez `undampened: true` ). Le site peut également être inclus dans les paramètres de l'action si une ventilation détaillée est souhaitée. (Le site optionnel peut être spécifié à l'aide de tirets ou de traits de soulignement.)

```yaml
action: solcast_solar.query_forecast_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
  undampened: true
  #site: 1111-aaaa-bbbb-2222
```

L'historique des prévisions non atténuées est conservé pendant seulement 14 jours.

#### Lecture des valeurs réelles estimées dans un système automatisé

Lors du calcul de l'amortissement à l'aide d'un système automatisé, il peut être avantageux d'utiliser comme données d'entrée des valeurs passées réelles estimées.

Ceci est possible grâce à l'action `solcast_solar.query_estimate_data` . Le site n'est peut-être pas inclus dans les paramètres de l'action actuellement. (Si vous souhaitez obtenir des informations détaillées sur le site, veuillez ouvrir un ticket ou une discussion.)

```yaml
action: solcast_solar.query_estimate_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
```

Les données réelles estimées sont conservées pendant 730 jours.

#### Valeurs d'amortissement de lecture

Les facteurs d'amortissement actuellement définis peuvent être récupérés à l'aide de l'action « Solcast PV Forecast : Obtenir l'amortissement des prévisions » ( `solcast_solar.get_dampening` ). Cette action peut spécifier un identifiant de site (facultatif), ou ne pas spécifier de site, ou encore sélectionner « all ». Si aucun site n'est spécifié, tous les sites pour lesquels un amortissement est défini seront renvoyés. Une erreur est générée si aucun amortissement n'est défini pour un site.

Le site optionnel peut être spécifié à l'aide de tirets ou de traits de soulignement. Si l'appel de service utilise des traits de soulignement, la réponse en utilisera également.

Si l'amortissement granulaire est configuré pour spécifier à la fois les facteurs d'amortissement de chaque site et les facteurs d'amortissement « tous sites », toute tentative de récupération des facteurs d'amortissement d'un site individuel renverra les facteurs d'amortissement « tous sites », la mention « tous sites » étant indiquée dans la réponse. En effet, dans ce cas, les facteurs d'amortissement « tous sites » prévalent sur les paramètres de chaque site.

Exemple d'appel :

```yaml
action: solcast_solar.get_dampening
data:
  site: b68d-c05a-c2b3-2cf9
```

Exemple de réponse :

```yaml
data:
  - site: b68d-c05a-c2b3-2cf9
    damp_factor: >-
      1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0
```

### configuration des attributs du capteur

De nombreux attributs de capteurs peuvent être utilisés comme source de données pour les capteurs modèles, les graphiques, etc., notamment une ventilation par site, des estimations des valeurs 10/50/90 et une ventilation détaillée par heure et par demi-heure pour chaque jour de prévision.

De nombreux utilisateurs n'utiliseront pas ces attributs ; par conséquent, afin de réduire l'encombrement (notamment au niveau de l'interface utilisateur et du stockage des statistiques de la base de données), tous ces attributs peuvent être désactivés s'ils ne sont pas nécessaires.

Par défaut, toutes ces options sont activées, à l'exception des prévisions détaillées par site et des données horaires détaillées. (Les attributs de détail horaires et semi-horaires sont exclus de l'envoi à l'enregistreur Home Assistant, car leur taille importante entraînerait une croissance excessive de la base de données et ils sont peu utiles à long terme.)

> [!NOTE]
>
> Si vous souhaitez implémenter l'exemple de graphique PV ci-dessous, vous devrez garder la ventilation détaillée par demi-heure activée, ainsi que `estimate10` .

### Configuration de limite stricte

Il existe une option permettant de définir une « limite stricte » pour la production prévue de l'onduleur, et cette limite « écrêtera » les prévisions de Solcast à une valeur maximale.

La limite maximale peut être définie comme une valeur globale (applicable à tous les sites et à tous les comptes Solcast configurés) ou par compte Solcast, avec une limite maximale distincte pour chaque clé API. (Dans ce dernier cas, séparez les limites maximales souhaitées par des virgules.)

Le cas d'utilisation de cette limite est simple, mais notez que très peu d'installations photovoltaïques y auront recours. (Et si vous utilisez des micro-onduleurs, ou un onduleur par chaîne, alors certainement pas. Il en va de même pour tous les panneaux ayant la même orientation sur un même site Solcast.)

Prenons l'exemple d'un onduleur de chaîne unique de 6 kW auquel sont raccordées deux chaînes de 5,5 kW chacune, orientées dans des directions opposées. Du point de vue de l'onduleur, cette configuration est considérée comme surdimensionnée. Il est impossible de paramétrer une limite de production CA dans Solcast adaptée à ce scénario avec deux sites, car en milieu de matinée ou d'après-midi en été, une chaîne peut produire 5,5 kW CC, soit 5 kW CA, et l'autre chaîne produira probablement également de l'énergie. Par conséquent, limiter la production CA de chaque chaîne à 3 kW (la moitié de l'onduleur) dans Solcast n'est pas pertinent. La limiter à 6 kW par chaîne l'est tout autant, car Solcast surestimera presque certainement la production potentielle.

La limite maximale peut être définie dans la configuration d'intégration ou via l'action de service `solcast_solar.set_hard_limit` des `Developer Tools` . Pour désactiver cette limite, saisissez la valeur 0 ou 100 dans la boîte de dialogue de configuration. Pour la désactiver via un appel de service, utilisez `solcast_solar.remove_hard_limit` . (La valeur 0 ne peut pas être spécifiée lors de l'exécution de l'action de définition.)

### Configuration des sites exclus

Il est possible d'exclure un ou plusieurs sites Solcast du calcul des totaux des capteurs et des prévisions du tableau de bord Énergie.

L'objectif est de permettre à un ou plusieurs sites « principaux » locaux d'afficher les valeurs prévisionnelles combinées globales, tandis qu'un site « distant » peut être visualisé séparément à l'aide de graphiques Apex et/ou de capteurs modèles dont les valeurs proviennent des attributs des capteurs de répartition des sites. Veuillez noter qu'il n'est pas possible de créer un flux distinct pour le tableau de bord Énergie à partir de capteurs modèles (ces données proviennent directement de l'intégration sous forme de dictionnaire de données).

L'utilisation de cette fonctionnalité avancée avec les capteurs modèles et les graphiques Apex n'est pas simple ; toutefois, des exemples sont fournis dans le fichier Lisez-moi pour les capteurs modèles créés à partir de données d'attributs et pour un graphique Apex. Consultez [les sections Interaction](#interacting) , [Exemples de capteurs modèles](#sample-template-sensors) et [Exemple de graphique Apex pour tableau de bord](#sample-apex-chart-for-dashboard) .

La configuration s'effectue via la boîte de dialogue `CONFIGURE` .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png" width="500">

La sélection des sites à exclure et le clic sur `SUBMIT` prendront effet immédiatement. Il n'est pas nécessaire d'attendre une mise à jour des prévisions.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png" width="500">

> [!NOTE]
>
> Les noms de sites et les identifiants de ressources proviennent des sites connus lors de la dernière récupération des données depuis Solcast (au démarrage). Il est impossible d'ajouter simultanément une nouvelle clé API et de sélectionner un site à exclure du nouveau compte. L'ajout du nouveau compte est indispensable ; l'intégration redémarrera alors et chargera les nouveaux sites. Vous pourrez ensuite sélectionner les sites à exclure.

### options de configuration avancées

Il est possible de modifier le comportement de certaines fonctions d'intégration, notamment pour l'amortissement automatisé intégré.

Ces options peuvent être définies en créant un fichier appelé `solcast-advanced.json` dans le répertoire de configuration Home Assistant Solcast Solar (généralement `/config/solcast_solar` ).

Pour connaître les options disponibles, consultez la documentation dans la [section Options avancées](https://github.com/BJReplay/ha-solcast-solar/blob/main/ADVOPTIONS.md) .

## Capteurs de gabarit d'exemple

### Combinaison des données du site

Il est possible que l'on souhaite combiner les données prévisionnelles de plusieurs sites communs à un compte Solcast, permettant ainsi la visualisation des données détaillées de chaque compte dans un graphique Apex.

Ce code est un exemple de la manière de procéder en utilisant un capteur modèle, qui additionne tous les intervalles de prévision pv50 pour donner un total de compte quotidien, et construit un attribut detailedForecast de toutes les données d'intervalle combinées à utiliser dans une visualisation.

Les ventilations par site doivent être activées dans les options d'intégration (la ventilation détaillée des prévisions n'est pas activée par défaut).

**Afficher le code**

<details><summary><i>Cliquez ici</i></summary>
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




## Exemple de graphique Apex pour tableau de bord

Le code YAML suivant génère un graphique de la production photovoltaïque actuelle, des prévisions de production photovoltaïque et des prévisions pour les 10 prochaines années. [Apex Charts](https://github.com/RomRider/apexcharts-card) doit être installé.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png">

Personnalisez votre installation avec les capteurs Home Assistant appropriés pour connaître la production solaire totale actuelle et la puissance de sortie des panneaux photovoltaïques.

> [!NOTE]
>
> Le graphique suppose que les capteurs photovoltaïques solaires sont en kW, mais si certains sont en W, ajoutez la ligne `transform: "return x / 1000;"` sous l'identifiant de l'entité pour convertir la valeur du capteur en kW.

**Afficher le code**

<details><summary><i>Cliquez ici</i></summary>
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




## Problèmes connus

- Modifier la limite maximale entraînera une modification de l'historique des prévisions enregistrées. Ce comportement est normal et ne devrait pas changer.
- Tous les fichiers JSON d'intégration de longueur nulle seront supprimés au démarrage (voir ci-dessous).
- Les sites d'exemple (si configurés dans votre tableau de bord Solcast) seront inclus dans vos prévisions récupérées par cette intégration et renvoyées à Home Assistant (voir ci-dessous).

### Suppression des fichiers de longueur nulle

Par le passé, il est arrivé que les fichiers cache soient écrits par l'intégration comme des fichiers vides. Ce phénomène est extrêmement rare et nous rappelle l'importance de sauvegarder régulièrement notre installation.

La cause pourrait être un problème de code (qui a été examiné à plusieurs reprises et probablement résolu dans la version 4.4.8), ou un facteur externe que nous ne pouvons pas contrôler, mais cela se produit certainement à l'arrêt, l'intégration (auparavant) ne parvenant pas à redémarrer, généralement après sa mise à niveau.

Les données ont disparu. La solution consistait à supprimer le fichier vide ou à restaurer le fichier à partir d'une sauvegarde, puis à redémarrer.

À partir de la version 4.4.10, le système démarrera en présence d'un fichier vide, avec un événement `CRITICAL` consigné indiquant que le fichier de taille nulle a été supprimé. Ceci entraînera une utilisation accrue de l'API au démarrage. ***Vous risquez de perdre l'historique de vos prévisions.***

Des problèmes d'utilisation de l'API sont à prévoir, mais ils seront résolus sous 24 heures.

### Sites d'échantillonnage

Si vous consultez des exemples de sites (comme ceux-ci) [](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png"> ) Supprimez-les de votre tableau de bord Solcast.

## Dépannage

<details><summary><i>Cliquez ici pour afficher plus de conseils de dépannage.</i></summary>
</details>

Cette intégration vise à minimiser la quantité d'informations consignées lorsque tout fonctionne correctement. En cas de problème, des entrées de journal `ERROR` ou `CRITICAL` seront générées, et des entrées de niveau `WARNING` en cas de problème temporaire ou mineur. Consultez toujours les journaux en premier lieu lors du dépannage.

Pour un journal plus détaillé, de nombreuses entrées sont générées au niveau `DEBUG` . L'activation de la journalisation de débogage est recommandée pour faciliter le dépannage. Veuillez noter que la modification du niveau de journalisation nécessite un redémarrage de Home Assistant, ce qui renomme le fichier `homeassistant.log` actuel en `homeassistant.log.1` (il n'existe pas `.2` ; seules la session actuelle et la précédente sont accessibles).

Dans `/homeassistant/configuration.yaml` :

```
logger:
  default: warn
  logs:
    custom_components.solcast_solar: debug
```

La consultation des journaux est assez simple, mais les journaux de débogage ne sont pas accessibles depuis l'interface utilisateur. Il faut consulter le fichier `/homeassistant/home-assistant.log` home-assistant.log`. Depuis une session SSH, utilisez la `less /homeassistant/home-assistant.log` . D'autres méthodes pour consulter ce fichier peuvent exister selon les extensions installées.

### Problèmes de clés API

Lors de la configuration, vous saisissez une ou plusieurs clés API. Les sites configurés sur solcast.com sont alors récupérés afin de tester la clé. En cas d'échec, les causes sont généralement limitées : clé incorrecte, absence de sites configurés sur le compte Solcast ou impossibilité d'accéder à solcast.com. Ces situations sont généralement faciles à identifier.

Si vous ne parvenez pas à accéder à solcast.com, veuillez généralement rechercher la cause du problème ailleurs. En cas de problème temporaire, comme l'affichage d'une erreur `429/Try again later` , suivez scrupuleusement les instructions : patientez, puis relancez la configuration initiale. (Le site de Solcast est généralement saturé de requêtes toutes les quinze minutes, et surtout en début d'heure.)

### Problèmes de mise à jour des prévisions

Lors d'une mise à jour des prévisions, le système intègre un mécanisme de nouvelle tentative pour gérer les situations transitoires d' `429/Try again later` . Il est très rare que les dix tentatives échouent, mais cela peut arriver tôt le matin, en Europe centrale. Dans ce cas, la mise à jour suivante aboutira presque certainement.

Un compteur d'utilisation de l'API est mis à jour pour suivre le nombre d'appels effectués vers solcast.com chaque jour (à partir de minuit UTC). Si ce compteur ne reflète pas la réalité, en cas de refus d'un appel à l'API, il sera réinitialisé à sa valeur maximale et ne le sera qu'à minuit UTC.

### Les valeurs prévues semblent « tout simplement fausses ».

Il est possible que des sites de démonstration soient encore configurés sur solcast.com. Vérifiez-le et, le cas échéant, supprimez-les.

Vérifiez également les paramètres d'azimut, d'inclinaison, de position et autres paramètres de vos sites. Des valeurs incorrectes ne sont pas dues à l'intégration, mais plutôt au problème de configuration générale.

### Exceptions dans les journaux

Les exceptions ne devraient être consignées qu'en cas de problème grave. Si elles le sont, c'est généralement un symptôme de la cause sous-jacente, et non un défaut du code, et elles ne sont généralement pas directement liées à la cause première du problème. Il faut rechercher les causes potentielles parmi les éléments qui ont changé.

En cas d'exceptions, il est probable que l'état des capteurs devienne `Unavailable` , ce qui est également un symptôme de la survenue d'une exception.

Si vous effectuez une « mise à niveau » depuis une intégration Solcast très ancienne ou complètement différente, il ne s'agit pas d'une mise à niveau, mais d'une migration. Certains scénarios de migration sont pris en charge, mais d'autres peuvent nécessiter la suppression complète de toutes les données incompatibles susceptibles de causer des problèmes importants. Consultez [la section « Suppression complète de l'intégration »](#complete-integration-removal) pour connaître l'emplacement des fichiers pouvant interférer.

Cela dit, des défauts de code peuvent survenir, mais ils ne doivent pas être la première chose à suspecter. Ce code est soumis à des tests automatisés approfondis avec PyTest avant chaque mise en production. Ces tests couvrent un large éventail de scénarios et exécutent chaque ligne de code. Certains de ces tests anticipent les situations les plus critiques pouvant provoquer des exceptions, comme la corruption de données en cache ; dans ces cas-là, des exceptions sont attendues.

### Dernier mot

Si vous rencontrez un comportement très étrange, avec de nombreuses exceptions, une solution rapide peut consister à sauvegarder tous les fichiers `/homeassistant/solcast*.json` , à les supprimer, puis à redémarrer l'intégration.




## Suppression complète de l'intégration

Pour supprimer complètement toute trace de l'intégration, commencez par accéder à `Settings` | `Devices & Services` | `Solcast PV Forecast` , cliquez sur les trois points à côté de l'icône d'engrenage ( `CONFIGURE` dans les premières versions de HA) et sélectionnez `Delete` .

À ce stade, les paramètres de configuration ont été réinitialisés, mais les caches de code et d'informations prévisionnelles existeront toujours (la reconfiguration de l'intégration réutilisera ces données mises en cache, ce qui peut être souhaitable ou non).

Les fichiers cache se trouvent dans le dossier de configuration Solcast Solar de Home Assistant (généralement `/config/solcast_solar` ou `/homeassistant/solcast_solar` , mais leur emplacement peut varier selon le type de déploiement de Home Assistant). Ces fichiers portent le nom de l'intégration et peuvent être supprimés avec `rm solcast*.json` .

Le code lui-même se trouve dans `/config/custom_components/solcast_solar` , et la suppression de ce dossier entier entraînera la suppression totale de l'intégration.

## Changements

v4.4.11

- Correction de la validation des options avancées pour `not_set_if` par @autoSteve
- Ajout des traductions manquantes (ES, FR, PL, SK, UR) par @GitLocalize
- Espacement cohérent des chaînes de caractères dans les fichiers par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.10...v4.4.11

v4.4.10

- Correction d'un problème réparable manquant dans les enregistrements par @autoSteve
- Correction d'un problème lié à l'absence d'historique des prévisions (#423) par @autoSteve
- Suppression des fichiers cache vides au démarrage par @autoSteve
- Ajout de l'option avancée granular_damping_delta_adjustment par @autoSteve
- Renommez automated_dampinging_no_delta_adjustment par @autoSteve
- Avertissement et problème de dépréciation concernant les options avancées par @autoSteve
- Ajout d'un problème signalé par @autoSteve concernant les erreurs liées aux options avancées.

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.9...v4.4.10

v4.4.9

- Ajout de variantes de modèles à amortissement automatique en option avancée par @Nilogax
- Ajout d'une option avancée de réglage automatique du delta d'amortissement par @Nilogax
- Ajout d'une option avancée d'amortissement automatique préservant les facteurs précédents par @Nilogax
- Ajout d'une option avancée de suppression automatique de l'amortissement par @autoSteve
- Ajout de la prise en charge de la plateforme de commutation pour l'entité de suppression de génération par @autoSteve
- L'entité de suppression peut désormais commencer et se terminer chaque jour dans n'importe quel état par @autoSteve
- Amélioration du comportement au démarrage et traduction des messages d'état au démarrage par @autoSteve
- Correction de la mise à jour de l'entité d'amortissement sur l'amortissement horaire défini par l'action à tous les niveaux 1.0 par @autoSteve
- Correction d'un bug mineur lié au démarrage lorsque les données réelles estimées n'ont pas encore été acquises par @autoSteve
- Correction d'une exception lors de l'utilisation de l'amortissement horaire lorsque l'entité d'amortissement est activée par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.8...v4.4.9

v4.4.8

- Déplacer tous les fichiers de cache et de configuration vers `config/solcast_solar` par @autoSteve
- L'ajout de l'API Solcast est temporairement indisponible, un problème signalé par @autoSteve
- Amélioration du message d'erreur « Prévisions futures manquantes lorsque la mise à jour automatique est activée » par @gcoan
- Ne suggérez pas de notification de réparation « réparable » pour la mise à jour manuelle suite aux échecs de l'API par @autoSteve
- Ignorer les facteurs d'amortissement automatiques ajustés au-dessus du seuil « insignifiant » par @autoSteve
- Ajout d'une option d'amortissement automatique avancée « facteur insignifiant ajusté » par @autoSteve
- Ajout de l'option d'amortissement automatique avancée « pic similaire » par @autoSteve
- Ajout d'une option avancée d'amortissement automatique « délai de récupération de la génération » par @autoSteve
- Ajout de l'option avancée d'estimation des données réelles « décomposition de la carte de journalisation » par @autoSteve
- Ajout de l'option avancée d'estimation des valeurs réelles « log ape percentiles » par @autoSteve
- Ajout de l'option avancée d'estimation des données réelles « délai de récupération » par @autoSteve
- Ajout de l'option générale avancée « agent utilisateur » par @autoSteve
- Modification de l'option avancée d'amortissement automatique « intervalles de correspondance minimaux » pour accepter `1` par @autoSteve
- Cohérence des attributs en tant que fuseau horaire local pour les valeurs de date et d'heure par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.7...v4.4.8

v4.4.7

- Ajout d'un fichier de configuration des options avancées par @autoSteve
- Ajout de l'attribut `custom_hours` au capteur `Forecast Next X Hours` par @autoSteve
- Amortissement automatique, amélioration de l'exclusion des générations non fiables par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.6...v4.4.7

v4.4.6

- Correction : Atténuation automatique, ignorer les jours de génération avec un petit nombre d’échantillons d’historique par @autoSteve
- Correction : Limitation de la modélisation de l’amortissement automatique à 14 jours (au lieu de l’historique des générations) par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.5...v4.4.6

v4.4.5

- Le passage à l'heure d'hiver en Europe/Dublin a été géré par @autoSteve.
- Auto-amortissement, utilisation de la détection d'anomalies interquartiles pour la génération d'entités par @autoSteve
- Amortissement automatique, adaptation aux entités de génération cohérentes au niveau de la génération ou au niveau du temps par @autoSteve
- Amortissement automatique, ignorer les intervalles de génération entiers présentant des anomalies par @autoSteve
- Amortissement automatique, le nombre minimum d'intervalles correspondants doit être supérieur à un par @autoSteve
- Amortissement automatique, ajout de la prise en charge des entités de suppression de génération par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.4...v4.4.5

v4.4.4

- Correction : Atténuation automatique, intervalle ajusté à l'heure d'été par @rcode6 et @autoSteve
- Suppression et suppression des problèmes d'azimut inhabituels ignorés par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.3...v4.4.4

v4.4.3

- Récupération aléatoire des données réelles, puis modélisation d'amortissement automatique immédiat par @autoSteve
- Exclure les entités à amortissement automatique désactivé de la sélection par @autoSteve
- Amortissement automatique, exclusion des intervalles à limitation d'exportation de tous les jours par @autoSteve
- Amortissement automatique, transitions vers l'heure d'été gérées par @autoSteve
- Obtenez jusqu'à quatorze jours de données prévisionnelles fournies par @autoSteve
- Correction : Mise à jour du tableau des facteurs d'amortissement dans TEMPLATES.md par @jaymunro
- Correction : Mise à jour du fichier TEMPLATES.md (erreur de frappe dans le nom du capteur) par @gcoan
- Version minimale de HA : 2025.3

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.2...v4.4.3

v4.4.2

- Amortissement automatique, prise en charge des entités de génération mises à jour périodiquement (Envoy) par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.1...v4.4.2

v4.4.1

- Ajustement automatique des unités de mesure de génération/exportation par @brilthor et @autoSteve
- Ignorer les sauts d'entités de génération atypiques par @autoSteve
- Exiger un accord majoritaire sur la génération de données réelles « bonne journée » pour l’amortissement automatique par @autoSteve
- Ajout d'un exemple de graphique à amortissement automatique (appliqué vs. base) au fichier TEMPLATES.md par @Nilogax. Merci !
- Mises à jour importantes du fichier README.md concernant l'amortissement automatique par @autoSteve, @gcoan et @Nilogax. Merci !
- Correction : Migration de l'utilisation sans réinitialisation, changement de clé, aucun changement de site par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.0...v4.4.1

v4.4.0

- Ajout d'une fonction d'amortissement automatique par @autoSteve
- Des facteurs d'amortissement modifiés sont appliqués dès le début de la journée par @autoSteve
- Correction d'un problème de dépassement de la taille maximale des attributs des capteurs traduits (par @autoSteve)
- Surveillez le fichier solcast-dampening.json pour les créations, mises à jour et suppressions effectuées par @autoSteve
- Ajout de l'attribut last_attempt à l'entité api_last_polled par @autoSteve
- Ajout du paramètre « autoriser l’action » avec un tiret ou un trait de soulignement par @autoSteve
- Ajout d'un test pour un azimut inhabituel par @autoSteve
- Correction des points de début/fin du tableau de bord Énergie par @autoSteve
- Attribution uniquement lorsque le crédit est dû à @autoSteve
- Version minimale de HA : 2024.11

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.5...v4.4.0

### Modifications antérieures

<details><summary><i>Cliquez ici pour revenir à la version 3.0.</i></summary>
</details>

v4.3.5

- Correction de la détection de changement de clé API (erreur 429) lors de l'utilisation de plusieurs clés (par @autoSteve)
- Correction d'un cas particulier de validation de clé pouvant empêcher le démarrage par @autoSteve
- Ajout d'attributs de comptage des échecs de mise à jour au dernier capteur interrogé par @autoSteve
- Autoriser la récupération des sites en cas d'échec toutes les 30 minutes dans la tempête 429 par @autoSteve
- Vérification de type plus stricte par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.4...v4.3.5

v4.3.4

- Inclure les balises de site sur le toit dans les attributs des capteurs de site par @autoSteve
- Suppression des messages de débogage critiques au démarrage, enregistrés par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.3...v4.3.4

v4.3.3

- Ajouter des sites à exclure des totaux et du tableau de bord Énergie par @autoSteve
- Ajout de la traduction portugaise par @ViPeR5000 (merci !)
- Nettoyage des capteurs de diagnostic de limite matérielle orphelins par @autoSteve
- Éviter le plantage lors du redémarrage de HA appelant de manière répétée roof_sites par @autoSteve
- Correction des valeurs des capteurs de diagnostic pour la limite stricte des clés API multiples par @autoSteve
- Correction de la suppression du cache orphelin lorsque la clé API contient des caractères non alphanumériques par @autoSteve
- Correction de la mise en forme de l'amortissement granulaire dans solcast-dampening.json (semi-indentation) par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.2...v4.3.3

v4.3.2

- Remplacez le tiret par un trait de soulignement dans les noms des attributs de répartition du site par @autoSteve
- Ajout de la traduction espagnole par @autoSteve
- Ajout de la traduction italienne par @Ndrinta (merci !)

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.1...v4.3.2

v4.3.1

- Ajout des instructions d'installation par défaut de HACS par @BJReplay

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.0...v4.3.1

v4.3.0

- Correction d'un problème survenu lorsque le détail par demi-heure était désactivé mais que le détail horaire était activé (par @autoSteve)
- Correction d'un problème de transition entre l'amortissement granulaire et l'amortissement hérité par @autoSteve
- Correction d'un problème lié à l'utilisation de plusieurs limites strictes par @autoSteve
- Correction d'un problème de démarrage obsolète lorsque la mise à jour automatique est activée par @autoSteve
- Ajout d'attributs de mise à jour automatique à api_last_polled par @autoSteve
- Mise à niveau des fichiers de données à partir du schéma d'intégration v3 par @autoSteve
- Les flux de configuration et d'options vérifient la validité de la clé API et la disponibilité des sites (par @autoSteve).
- Ajout des flux de réauthentification et de reconfiguration par @autoSteve
- Ajout de flux de réparation pour les prévisions qui ne se mettent pas à jour par @autoSteve
- Récupérer les estimations réelles sur un démarrage très ancien par @autoSteve
- Désactivation des capteurs en cas d'échec d'intégration par @autoSteve
- Détecter la clé API en double spécifiée par @autoSteve
- Suppression de la vérification des conflits d'intégration par @autoSteve
- Ajout de tests d'intégration et unitaires par @autoSteve
- Vérification stricte des types par @autoSteve
- Ajout d'une section de dépannage dans le fichier README.md par @autoSteve
- Correction d'un problème de prévisions incorrectes : les notes indiquent de supprimer les sites d'exemple du tableau de bord Solcast (par @BJReplay).
- Modèle de problème mis à jour par @BJReplay

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.7...v4.3.0

v4.2.7

- Correction d'un problème de validation des clés API par @autoSteve
- Correction d'un problème empêchant la suppression propre de l'intégration par @autoSteve
- Amélioration de la vérification des conflits d'intégration par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.6...v4.2.7

v4.2.6

- Correction d'un problème qui empêchait les nouvelles installations par @autoSteve
- Correction d'un problème de calcul de l'intervalle de mise à jour automatique pour les clés multi-API par @autoSteve
- Correction d'un problème de migration vers/depuis une configuration multi-API pour Docker par @autoSteve
- Correction d'un problème d'effacement de l'historique des prévisions par @autoSteve
- Correction d'un problème où le compteur d'API n'était pas incrémenté lors d'une récupération de démarrage obsolète par @autoSteve
- Correction d'un problème où l'API utilisée/le nombre total et la dernière mise à jour des capteurs n'étaient pas mis à jour par @autoSteve
- Ajout d'un simulateur d'API Solcast pour faciliter le développement et accélérer les tests (par @autoSteve)

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.5...v4.2.6

v4.2.5

- Ajout d'une limite stricte pour plusieurs clés API par @autoSteve
- Limiter proportionnellement les pannes de site par @autoSteve
- Calculer correctement le total quotidien des visites en fonction de la limite stricte par @autoSteve
- Application immédiate de l'atténuation aux prévisions futures par @autoSteve
- Correction des problèmes de transition vers l'heure d'été par @autoSteve
- Correction d'une exception de sortie d'état du système par @autoSteve
- Améliorations apportées à la journalisation pour une meilleure connaissance de la situation par @autoSteve
- La mise à jour automatique tolère un redémarrage juste avant la récupération planifiée par @autoSteve
- Mise à jour de la traduction polonaise, grâce à @erepeo

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.4...v4.2.5

v4.2.4

- Ajout de l'en-tête User-Agent aux appels API par @autoSteve
- Veuillez vous référer à l'action plutôt qu'à l'appel de service par @gcoan

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.3...v4.2.4

v4.2.3

- Correction d'un problème empêchant la modification des comptes Solcast par @autoSteve
- Correction d'un problème lié aux clés multi-API où la réinitialisation de l'utilisation de l'API n'était pas gérée correctement par @autoSteve
- Correction d'un problème lié à l'activation de la ventilation détaillée du site pour les attributs horaires par @autoSteve
- Nettoyage et refactorisation du code par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.0...v4.2.3

v4.2.1 / v4.2.2

- Versions retirées en raison d'un problème

v4.2.0

- Version préliminaire des fonctionnalités v4.1.8 et v4.1.9 disponible pour tous
- Traductions des réponses d'erreur des appels de service par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.2.0

Dernières modifications : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.9...v4.2.0

version préliminaire v4.1.9

- Amortissement granulaire par période de 30 minutes par @autoSteve et @isorin
- L'atténuation est appliquée lors de la récupération des prévisions et non à l'historique des prévisions par @autoSteve et @isorin
- Récupérer les valeurs prévisionnelles non atténuées à l'aide de l'appel de service par @autoSteve (merci @Nilogax)
- Obtenez les facteurs d'amortissement actuellement configurés grâce à l'appel de service de @autoSteve (merci @Nilogax)
- Migration des prévisions non amorties vers le cache non amorti au démarrage par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.8...v4.1.9

version préliminaire v4.1.8

- Mises à jour automatiques des prévisions qui ne nécessitent aucune intervention de @autoSteve et @BJReplay
- Amortissement par site ajouté par @autoSteve
- Ajout d'une option de ventilation détaillée du site pour des prévisions plus précises par @autoSteve
- Ajout d'une configuration de limite stricte aux options par @autoSteve
- Suppression du rechargement de l'intégration lorsque de nombreuses options de configuration sont modifiées par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.1.8

v4.1.7

- Correction des problèmes d'affichage des sites ajoutés ultérieurement par @autoSteve
- Correction des problèmes de dégradation du site pour les capteurs cannelés par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.6...v4.1.7

v4.1.6

- Simplifier le dialogue de configuration par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.5...v4.1.6

version préliminaire v4.1.5

- Bug : L’horodatage stocké dans le cache d’utilisation était incorrect (par @autoSteve)
- Bug : Ajout de la réinitialisation de la clé API pour la première clé par @autoSteve
- Bug : Itérateur manquant dans la vérification des nouveaux sites par @autoSteve
- Solution de contournement pour un possible bug de planification de HA par @autoSteve
- Alignement du style de code avec les directives de style HA par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.4...v4.1.5

v4.1.4 préversion

- Mise à jour de la traduction polonaise par @home409ca
- Renommer l'intégration dans HACS en Solcast PV Forecast par @BJReplay
- Réduction de la version requise pour aiofiles à &gt;=23.2.0 par @autoSteve
- Améliorations apportées à la boîte de dialogue de configuration par @autoSteve
- Mises à jour diverses des traductions par @autoSteve
- Moment de refactorisation et construction de spline restante par @autoSteve
- Prévenir les prévisions négatives pour le capteur de l'heure X par @autoSteve
- Suppression du rebond de la spline pour réduire la spline par @autoSteve
- Sérialisation plus soignée de solcast.json par @autoSteve
- Surveiller l'horodatage de la dernière mise à jour du fichier sites-usage.json par @autoSteve
- Nettoyage important du code par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.3...v4.1.4

v4.1.3

- Prendre en compte la suppression de l'appel API GetUserUsageAllowance par @autoSteve
- Réduction de moitié des délais de nouvelle tentative par @autoSteve
- Améliorations du fichier Lisez-moi par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.2...v4.1.3

v4.1.2

- Quart de travail de quinze minutes, car les moyennes de 30 minutes sont calculées par @autoSteve
- Augmenter à dix le nombre de tentatives de récupération des prévisions par @autoSteve
- Déplacer les images vers des captures d'écran par @BJReplay
- Correction du problème d'affichage des images du fichier README dans l'interface HACS

Remplace la version 4.1.1

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.0...v4.1.2

v4.1

- Première version majeure depuis la v4.0.31 qui n'était pas considérée comme une pré-version.
- Les versions précédentes ont été pour la plupart assez stables, mais nous sommes convaincus que celle-ci est prête pour tous.
- Modifications apportées depuis la version 4.0.31 :
    - Stabilité grandement améliorée pour tous et expérience de démarrage initiale simplifiée pour les nouveaux utilisateurs
    - Attributs supplémentaires du capteur
    - Nouvelles options de configuration pour supprimer les attributs des capteurs
    - Rédaction des informations sensibles dans les journaux de débogage
    - Efficacité accrue, avec de nombreux capteurs calculés à intervalles de cinq minutes, certains uniquement lors de la récupération des prévisions.
    - Interpolation spline pour les capteurs « instantanés » et « périodiques ».
    - Correctifs pour les utilisateurs de plusieurs clés API
    - Correctifs pour les utilisateurs de Docker
    - Améliorations de la gestion des exceptions
    - Améliorations de la journalisation
- @autoSteve est le bienvenu en tant que propriétaire du code.
- Il apparaît désormais clairement qu'il est peu probable que ce dépôt soit ajouté comme dépôt par défaut dans HACS avant la sortie de HACS 2.0. Par conséquent, les instructions d'installation indiquent clairement que l'ajout via la procédure de dépôt manuel est l'approche privilégiée, et de nouvelles instructions ont été ajoutées pour montrer comment procéder.

Journal des modifications de la version : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.1.0

Dernières modifications : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.43...v4.1.0

v4.0.43

- Récupération automatique au démarrage lorsque des données de prévision obsolètes sont détectées par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.42...v4.0.43

v4.0.42

- Signalement des échecs de chargement initiaux des sites et nouvelles tentatives automatiques HA par @autoSteve
- Suppression du rebond des splines dans les splines de moment par @autoSteve
- Recalculer les splines à minuit avant la mise à jour des capteurs par @autoSteve
- Mises à jour du fichier Lisez-moi par @autoSteve
- Suppression des seuils d'atténuation et de limite stricte dans les prévisions détaillées par site (trop stricts, trop trompeurs) par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.41...v4.0.42

v4.0.41

- Prévision interpolée 0/30/60 correction n° 101 par @autoSteve
- Assurez-vous que le répertoire de configuration est toujours relatif à l'emplacement d'installation #98 par @autoSteve
- Ajouter state_class à `power_now_30m` et `power_now_1hr` pour correspondre `power_now` de @autoSteve (supprimera LTS, mais LTS n'est pas utile pour ces capteurs)
- Utiliser les splines quotidiennes des valeurs prévisionnelles momentanées et décroissantes par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.40...v4.0.41

v4.0.40

- Prévisions interpolées de puissance et d'énergie 0/30/60 x heures par @autoSteve
- Assurez-vous que le répertoire de configuration est toujours relatif à l'emplacement d'installation (par @autoSteve).
- Améliorations apportées au graphique PV par @gcoan

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.39...v4.0.40

v4.0.39

- Mise à jour des descriptions des capteurs et modification de certains noms de capteurs par @isorin (Cela peut entraîner des dysfonctionnements de l'interface utilisateur, des automatisations, etc. si ces capteurs sont utilisés. Alimentation en 30/60 minutes et capteur personnalisé sur X heures).
- Suppression de la dépendance à la bibliothèque scipy par @autoSteve
- Ajout d'options de configuration granulaires pour les attributs par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.38...v4.0.39

v4.0.38

- Ajout des concepts clés de Solcast et d'un exemple de graphique de production photovoltaïque au fichier README par @gcoan
- Ajout d'une spline PCHIP pour prévoir le reste par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.37...v4.0.38

v4.0.37

- Modification du nommage des attributs pour supprimer « pv_ » par @autoSteve (remarque : cette modification entraînera une rupture si les nouveaux attributs ont déjà été utilisés dans des modèles/automatisations).
- Arrondi des attributs de capteur n° 51 par @autoSteve
- Amélioration de la gestion des exceptions pour la récupération des prévisions par @autoSteve
- Amélioration de la gestion des exceptions pour la récupération des prévisions par @autoSteve
- Remplacer l'exception par un avertissement #74 par @autoSteve
- Nouvelle tentative de chargement initial/en cache inexpliqué par @autoSteve
- Journalisation de débogage moins bruyante par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.36...v4.0.37

v4.0.36

- (Amélioration) Ajout d'attributs de capteur (estimation/estimation10/estimation90) et améliorations de la journalisation par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.35...v4.0.36

v4.0.35

- (Amélioration) Ventilation des prévisions de puissance et de temps pour chaque site en tant qu'attributs par @autoSteve
- Ne pas consigner la mise à jour des options de version si aucune mise à jour n'est requise par @autoSteve
- Ajout d'informations sur la préservation de l'historique et de la configuration d'Oziee à la bannière par @iainfogg

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.34...v4.0.35

v4.0.34

- Corriger la fonction query_forecast_data afin que les prévisions historiques à court terme soient renvoyées par @isorin
- En cas d'échec des appels à l'API roofing/usage lors du rechargement, le cache est utilisé instantanément, ce qui peut réduire le temps de démarrage (par @autoSteve).
- En cas de délai d'attente dépassé lors d'un appel asynchrone à la fonction get de sites, le cache sera utilisé s'il existe (par @autoSteve).
- Améliorations importantes de la journalisation par @autoSteve
- Il arrive que le cache des sites soit créé incorrectement avec la clé API ajoutée, alors qu'il n'y a qu'une seule clé API (par @autoSteve).
- Suppression des coordonnées de latitude/longitude dans les journaux de débogage par @autoSteve
- Suppression probable des avertissements de « comptage » par @autoSteve
- Correction du mécanisme de nouvelle tentative d'utilisation de l'API par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.33...v4.0.34

v4.0.33

- Améliorations des performances pour les mises à jour des capteurs par @isorin, notamment :
    - L'intervalle de mise à jour des capteurs a été réduit à 5 minutes.
    - Répartissez les capteurs en deux groupes : les capteurs qui doivent être mis à jour toutes les 5 minutes et les capteurs qui ne doivent être mis à jour que lorsque les données sont actualisées ou que la date change (valeurs quotidiennes).
    - Correction de problèmes liés à la suppression des prévisions antérieures (plus de 2 ans) et à un code défectueux
    - Améliorer la fonctionnalité des prévisions : par exemple, la prévision « forecast_remaining_today » est mise à jour toutes les 5 minutes en calculant l’énergie restante sur l’intervalle de 30 minutes actuel. Même chose pour les capteurs « now/next hour ».
- Suppression de la clé API Solcast dans les journaux par @isorin
- Rétablissement des options de mise à jour asynchrone Oziee '4.0.23' #54 par @autoSteve, qui causaient des problèmes de ralentissement des mises à jour.

Commentaire de @isorin : «* J’utilise la fonction forecast_remaining_today pour déterminer l’heure de la journée à laquelle commencer à charger les batteries afin qu’elles atteignent un niveau de charge prédéterminé le soir. Grâce à mes modifications, c’est possible.* »

À cela, je réponds : bravo !

Nouveaux contributeurs

- @isorin a effectué sa première contribution dans https://github.com/BJReplay/ha-solcast-solar/pull/45

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.32...v4.0.33

v4.0.32

- Correction de bug : Compteur d’utilisation de l’API indépendant pour chaque compte Solcast par @autoSteve
- Correction de bug : Forcer tous les caches à utiliser /config/ pour toutes les plateformes (corrige les déploiements Docker) #43 par @autoSteve
- Amélioration du choix des options de journalisation (débogage, info, avertissement) pour la récupération/nouvelle tentative de prévision par @autoSteve
- Suppression des requêtes de prévisions consécutives à moins de quinze minutes d'intervalle (corrige les requêtes multiples inattendues en cas de redémarrage au moment précis où l'automatisation de la requête est déclenchée) par @autoSteve
- Solution de contournement : Prévenir l’erreur lorsque « tally » est indisponible lors d’une nouvelle tentative par #autoSteve
- Correction d'un problème rencontré avec les versions antérieures de HA qui ne reconnaissaient pas `version=` pour `async_update_entry()` #40 par autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.0.32

v4.0.31

- Documentation : Modifications apportées au fichier README.md
- docs : Ajouter des notes de dépannage.
- Documentation : Fusionner les notes de modification du fichier info.md dans le fichier README.md
- documentation : Configurer pour que HACS affiche le fichier README.md

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.30...v4.0.31

v4.0.30

- Correction de bug : Prise en charge de la mise en cache de plusieurs sites de comptes Solcast
- Correction de bug : Le mécanisme de nouvelle tentative lorsque le regroupement des sites sur les toits réussit était défectueux.

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.29...v4.0.30

v4.0.29

- Correction de bug : Écriture du cache d’utilisation de l’API à chaque interrogation réussie par @autoSteve dans https://github.com/BJReplay/ha-solcast-solar/pull/29
- Correction de bug : la limite d’API par défaut est désormais de 10 pour pallier l’échec de l’appel initial (par @autoSteve).
- Augmenter le nombre de tentatives GET des sites de deux à trois par @autoSteve

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.28...v4.0.29

v4.0.28

- Ajout d'une nouvelle tentative pour les sites sur les toits (collection #12) par @autoSteve dans https://github.com/BJReplay/ha-solcast-solar/pull/26
- Modifications complètes du fichier info.md depuis la version 4.0.25
- Réintégration de la plupart des modifications apportées à oziee v4.0.23 par @autoSteve
- Conserver les données mises en cache lorsque la limite de l'API est atteinte.

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.27...v4.0.28

Nouveau collaborateur

- @autoSteve a apporté une contribution énorme ces derniers jours - il a un bouton de sponsor sur son profil, alors n'hésitez pas à cliquer dessus !

v4.0.27

- Documentation : Mise à jour du fichier info.md par @Kolbi dans https://github.com/BJReplay/ha-solcast-solar/pull/19
- Utilisez aiofiles avec ouverture asynchrone, attendez data_file par @autoSteve dans https://github.com/BJReplay/ha-solcast-solar/pull/21
- Ajout de la prise en charge de la fonction async_get_time_zone() par @autoSteve dans https://github.com/BJReplay/ha-solcast-solar/pull/25

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.26...v4.0.27

Nouveaux contributeurs

- @Kolbi a effectué sa première contribution dans https://github.com/BJReplay/ha-solcast-solar/pull/19
- @autoSteve a effectué sa première contribution dans https://github.com/BJReplay/ha-solcast-solar/pull/21

v4.0.26

- Corrections #8 #9 #10 - Ma catégorie de boutons HA par @mZ738 dans https://github.com/BJReplay/ha-solcast-solar/pull/11
- Mise à jour du fichier README.md par @wimdebruyn dans https://github.com/BJReplay/ha-solcast-solar/pull/5
- Préparez-vous pour la nouvelle version de @BJReplay sur https://github.com/BJReplay/ha-solcast-solar/pull/13

Journal des modifications complet : https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.25...v4.0.26

Nouveaux contributeurs

- @mZ738 a effectué sa première contribution dans https://github.com/BJReplay/ha-solcast-solar/pull/11
- @wimdebruyn a effectué sa première contribution dans https://github.com/BJReplay/ha-solcast-solar/pull/5

v4.0.25

- Soumission HACS

v4.0.24

- Modifications supplémentaires pour supprimer les liens vers https://github.com/oziee qui avaient été oubliés lors de la première tentative.
- D'autres modifications sont à prévoir avant de soumettre le dossier à HACS.

v4.0.23

- Propriétaire modifié : @BJReplay
- Le dépôt GitHub a été modifié et se trouve désormais à l'adresse suivante : https://github.com/BJReplay/ha-solcast-solar

v4.0.22

- Cette fois-ci, le capteur météo a disparu... et la réinitialisation UTC à minuit fonctionne
- (*) Ajout d'une option de configuration pour définir une limite stricte pour les onduleurs avec des panneaux solaires surdimensionnés. *99,9999999 % des utilisateurs n'auront jamais besoin de configurer cette option (0,00000001 % est @CarrapiettM).

v4.0.21

- J'ai retiré le capteur météorologique car il ne cesse de dysfonctionner.

v4.0.20

- Correction de l'erreur d'information pour `solcast_pv_forecast_forecast_today (<class 'custom_components.solcast_solar.sensor.SolcastSensor'>) is using state class 'measurement' which is impossible considering device class ('energy')`
- Suppression de la récupération UTC à minuit et remplacement par une valeur nulle afin de réduire la charge sur le système Solcast ⚠️ Pour limiter l'impact sur le serveur Solcast, Solcast demande aux utilisateurs de configurer leurs automatisations d'interrogation avec un intervalle de minutes et de secondes aléatoire. Par exemple, si votre interrogation a lieu à 10h00, configurez-la à 10h04min10 afin d'éviter que tous les utilisateurs n'interrogent les services simultanément.

v4.0.19

- Correction d'un problème où la réinitialisation de la limite/utilisation de l'API ne mettait pas à jour l'interface utilisateur de Home Assistant.

v4.0.18

- La valeur fixe du capteur météorologique ne se conserve pas
- Réinitialiser la limite de l'API et les capteurs d'utilisation à minuit UTC (réinitialisation de l'utilisation)

v4.0.17

- Traduction slovaque mise à jour, merci @misa1515
- ajout d'un capteur pour la description météo Solcast

v4.0.16

- L'idée de @Zachoz d'ajouter une option permettant de sélectionner la valeur du champ d'estimation Solcast pour les calculs de prévision (estimate, estimate10 ou estimate90) a été ajoutée. ESTIMATE : prévisions par défaut. ESTIMATE10 : prévisions à 10 jours (scénario plus nuageux que prévu). ESTIMATE90 = Prévisions 90 - scénario moins nuageux que prévu

v4.0.15

- Ajout d'un capteur personnalisé « Prochaines X heures ». Vous sélectionnez le nombre d'heures à prendre en compte.
- Ajout de la traduction française grâce à @Dackara
- ajout de quelques capteurs à inclure dans les données statistiques HA

v4.0.14

- Les valeurs d'attributs modifiées provenant des sites situés sur les toits empêchent l'ajout de repères aux cartes (HA ajoute automatiquement l'élément à la carte si les attributs contiennent des valeurs de latitude/longitude).
- Ajout de l'ourdou grâce à @yousaf465

v4.0.13

- Ajout de la traduction slovaque grâce à @misa1515
- Délai d'expiration de la connexion par interrogation étendu de 60 s à 120 s
- ajout de points de sortie de débogage supplémentaires pour la vérification des données
- L'attribut `dataCorrect` des nouvelles données de prévision renvoie True ou False selon que les données sont complètes pour ce jour-là.
- Suppression `0 of 48` messages de débogage pour les prévisions du 7e jour, car si l'API n'est pas interrogée à minuit, les données sont incomplètes pour le 7e jour (limitation du nombre maximal d'enregistrements renvoyés par Solcast).

v4.0.12

- La version bêta de HA 2023.11 empêche l'affichage des capteurs dans la `Configuration` . Les capteurs de toit ont été déplacés vers `Diagnostic`

v4.0.11

- meilleure gestion lorsque les données sont incomplètes pour certains capteurs

v4.0.10

- Corrections pour la modification de la clé API une fois qu'elle a déjà été définie.

v4.0.9

- nouveau service de mise à jour des prévisions horaires des facteurs d'amortissement

v4.0.8

- Ajout de la traduction polonaise grâce à @home409ca
- Ajout d'un nouvel `Dampening` à la configuration d'intégration Solcast

v4.0.7

- meilleure gestion lorsque le site Solcast ne renvoie pas correctement les données de l'API

v4.0.6

- Erreurs corrigées de division par zéro en l'absence de données renvoyées
- Valeur prévisionnelle restante fixe pour aujourd'hui. Inclut désormais la prévision par tranches de 30 minutes dans le calcul.

v4.0.5

- PR n° 192 - Traduction allemande mise à jour… merci @florie1706
- Prévisions corrigées `Remaining Today` … elles utilisent désormais également les données à intervalle de 30 minutes.
- Correction d'un problème d'erreur lors `Download diagnostic` .

v4.0.4

- L'appel de service `query_forecast_data` a été terminé afin d'interroger les données de prévision. Il renvoie une liste de données de prévision utilisant une plage de dates et d'heures de début et de fin.
- Et c'est tout… sauf si Home Assistant apporte des modifications majeures ou s'il y a un bug important dans la version 4.0.4, il s'agit de la dernière mise à jour.

v4.0.3

- Mise à jour de la version allemande grâce à @florie1706 PR#179 et suppression de tous les autres fichiers de localisation
- Ajout d'un nouvel attribut `detailedHourly` à chaque capteur de prévision journalière, affichant les prévisions horaires en kWh.
- En cas de données manquantes, les capteurs afficheront tout de même des informations, mais un journal de débogage indiquera que le capteur présente des données manquantes.

v4.0.2

- Les noms des capteurs **ont** changé ! Cela est dû aux chaînes de localisation de l'intégration.
- La précision décimale des prévisions de demain est passée de 0 à 2.
- Correction des données manquantes des prévisions à 7 jours qui étaient ignorées
- Ajout d'un nouveau capteur `Power Now`
- Ajout d'un nouveau capteur `Power Next 30 Mins`
- Ajout d'un nouveau capteur `Power Next Hour`
- Localisation ajoutée pour tous les objets de l'intégration. Merci à @ViPeR5000 de m'avoir donné l'idée (traduction Google utilisée ; si vous trouvez des erreurs, veuillez soumettre une pull request et je mettrai à jour les traductions).

v4.0.1

- Rebasé sur la version 3.0.55
- conserve les données prévisionnelles des 730 derniers jours (2 ans).
- Certains capteurs ont vu leurs propriétés device_class et native_unit_of_measurement mises à jour vers le type correct.
- Le nombre d'interrogations de l'API est lu directement depuis Solcast et n'est plus calculé.
- L'interrogation automatique est terminée. Il appartient désormais à chacun de créer une automatisation pour interroger les données à la demande. Ceci est dû au fait que de nombreux utilisateurs n'effectuent plus que 10 appels API par jour.
- Les données de sauvegarde de l'heure UTC ont été supprimées, tandis que les données solcast ont été conservées telles quelles afin que les données de fuseau horaire puissent être modifiées en cas de besoin.
- Les données d'historique ont disparu suite au changement de nom du capteur. L'historique Home Assistant n'est plus utilisé ; les données sont désormais stockées dans le fichier solcast.json.
- Suppression de la mise à jour du service : les données réelles de Solcast ne sont plus collectées (elles étaient utilisées lors de la première installation pour obtenir les données historiques afin que l’intégration fonctionne et que je ne reçoive pas de rapports d’incidents, car Solcast ne fournit pas les données d’une journée complète, mais uniquement celles de la période où l’on effectue un appel).
- De nombreux messages de journalisation ont été mis à jour et affichent désormais les mentions « débogage », « information », « avertissement » ou « erreur ».
- Il est possible que certains **capteurs** ne possèdent plus de valeurs d'attributs supplémentaires, ou que ces valeurs aient été renommées ou modifiées par rapport aux données stockées.
- des données de diagnostic plus détaillées à partager en cas de besoin pour aider à résoudre les problèmes
- Une partie du travail de @rany2 a été intégrée.

Supprimé 3.1.x

- Trop d'utilisateurs n'ont pas pu maîtriser la puissance de cette version.
- La version 4.xx remplace les versions 3.0.55 à 3.1.x et apporte de nouvelles modifications.

v3.0.47

- Ajout de l'attribut nom du jour de la semaine pour les prévisions des capteurs : aujourd'hui, demain, D3…7. Ces noms peuvent être lus via le modèle : {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_tomorrow', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D3', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D4', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D5', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D6', 'nom_du_jour') }} {{ state_attr('sensor.solcast_forecast_D7', 'nom_du_jour') }}

v3.0.46

- Problème possible avec MariaDB - solution possible

v3.0.45

- pré-sortie
- actuellement en cours d'essai
- L'installation ne fera de mal à personne.

v3.0.44

- pré-sortie
- meilleures données de diagnostic
- juste pour tester
- L'installation ne fera de mal à personne.

v3.0.43

- Version préliminaire, ne pas utiliser !
- Ne pas installer :) juste pour tester

v3.0.42

- Correction d'un problème d'appel double au service de mise à jour des prévisions

v3.0.41

- Journalisation remaniée. Reformulation. Davantage de journaux de débogage, d'informations et d'erreurs.
- Le compteur d'utilisation de l'API n'a pas été enregistré lors de sa réinitialisation à zéro à minuit UTC.
- Nous avons ajouté un nouveau service permettant de demander la mise à jour des données réelles de Solcast pour les prévisions.
- ajout des informations de version à l'interface utilisateur d'intégration

v3.0.40

- Quelqu'un a laissé du code inutilisé dans la version 3.0.39, ce qui cause des problèmes.

v3.0.39

- Informations sur la version supprimées

v3.0.38

- Correction d'erreur avec la version 3.0.37 pour la mise à jour des capteurs

v3.0.37

- Assurez-vous que les capteurs horaires se mettent à jour lorsque l'interrogation automatique est désactivée.

v3.0.36

- comprend tous les articles de pré-lancement
- Les données historiques exactes sont désormais interrogées auprès de l'API uniquement à midi et en fin de journée (donc seulement deux fois par jour).

v3.0.35 - PRÉ-VERSION

- le délai d'expiration de la connexion Internet a été prolongé à 60 secondes.

v3.0.34 - PRÉ-VERSION

- Service ajouté pour supprimer l'ancien fichier solcast.json afin de repartir sur de bonnes bases.
- Renvoyer des données de graphique d'énergie vides en cas d'erreur lors de la génération des informations

v3.0.33

- ajout de capteurs pour les prévisions à 3, 4, 5, 6 et 7 jours.

v3.0.32

- exigences d'appel de fonction de configuration HA refactorisées
- J'ai corrigé du code contenant des fautes de frappe pour corriger l'orthographe des mots... rien de grave.

v3.0.30

- Intégration de certaines contributions de @696GrocuttT dans cette version
- Correction de code liée à l'utilisation de la totalité du nombre d'API autorisées.
- Cette mise à jour risque fort de perturber le compteur API actuel, mais après la réinitialisation du compteur UTC, tout rentrera dans l'ordre pour le comptage des API.

v3.0.29

- Le capteur « Heures de pointe aujourd'hui/demain » a été modifié et est passé de la date à l'heure.
- J'ai rétabli l'unité de mesure de pointe en Wh, car le capteur indique les heures de pointe/maximum prévues pour l'heure.
- Une nouvelle option de configuration a été ajoutée à l'intégration pour désactiver l'interrogation automatique. Les utilisateurs peuvent ainsi configurer leur propre automatisation pour interroger les données à leur convenance (principalement parce que Solcast a limité à 10 le nombre d'interrogations API par jour pour les nouveaux comptes).
- Le compteur d'API affiche désormais le total utilisé au lieu du quota restant, car certains ont 10 API et d'autres 50. Il affichera « Nombre d'API dépassé » si vous n'avez plus d'API disponibles.

v3.0.27

- Unité modifiée pour la mesure de crête n° 86. Merci Ivesvdf.
- quelques autres modifications mineures de texte pour les journaux
- Changement d'appel de service, merci 696GrocuttT
- y compris la correction du problème n° 83

v3.0.26

- correctif de test pour le problème n° 83

v3.0.25

- Suppression de la PR pour la version 3.0.24 - provoquait des erreurs dans le graphique de prévision
- Correction d'un problème d'ajout de prévisions au tableau de bord solaire dans HA 2022.11

v3.0.24

- PR fusionnée de @696GrocuttT

v3.0.23

- ajout de code de journalisation de débogage supplémentaire
- ajout du service de mise à jour des prévisions

v3.0.22

- ajout de code de journalisation de débogage supplémentaire

v3.0.21

- Ajout de journaux de débogage supplémentaires pour plus d'informations.

v3.0.19

- CORRECTION : coordinator.py, ligne 133, dans update_forecast pour update_callback dans self._listeners : RuntimeError : la taille du dictionnaire a changé pendant l’itération
- Cette version nécessite désormais HA 2022.7 ou une version ultérieure.

v3.0.18

- calculs modifiés de la valeur de retour du compteur d'API

v3.0.17

- Configurez l'heure de l'API d'interrogation à 10 minutes après l'heure pour laisser à l'API Solcast le temps de calculer les données satellitaires.

v3.0.16

- Correction de l'interrogation de l'API pour obtenir des données réelles de temps en temps pendant la journée
- Ajout du chemin complet vers le fichier de données - merci OmenWild

v3.0.15

- Fonctionne dans les versions bêta 2022.6 et 2022.7.

v3.0.14

- corrige les erreurs de HA 2022.7.0b2 (il semble que oui :) )

v3.0.13

- Les données graphiques précédentes n'ont pas été réinitialisées à minuit, heure locale.
- importation asyncio manquante

v3.0.12

- Les données représentées graphiquement pour la semaine/le mois/l'année n'étaient pas ordonnées, ce qui rendait le graphique confus.

v3.0.11

- Ajout d'un délai d'expiration pour les connexions au serveur API Solcast
- Ajout des données graphiques des 7 derniers jours au tableau de bord énergétique (fonctionne uniquement si vous enregistrez des données).

v3.0.9

- **Les utilisateurs effectuant une mise à jour depuis la version 3.0.5 ou une version antérieure doivent supprimer le fichier « solcast.json » dans le répertoire HA&gt;config pour éviter toute erreur.**
- Les capteurs ont été renommés avec le préfixe « solcast_ » pour faciliter leur identification.
- ** En raison du changement de nom, des doublons de capteurs apparaîtront dans l'intégration. Ils seront grisés dans la liste ou afficheront des valeurs telles que « inconnu » ou « indisponible ». Supprimez simplement ces anciens capteurs un par un de l'intégration. **

v3.0.6

- **Les utilisateurs effectuant une mise à niveau depuis la version 3.0.x doivent supprimer le fichier « solcast.json » dans le répertoire HA&gt;config**
- J'ai corrigé plein de petits bugs et problèmes.
- Il est désormais possible d'ajouter plusieurs comptes Solcast. Il suffit de séparer les clés API par une virgule dans la configuration d'intégration.
- Le compteur d'API restantes indique le nombre d'API restantes plutôt que le nombre d'API utilisées.
- Les données de « prévision réelle » ne sont désormais demandées qu'une seule fois, lors du dernier appel API au coucher du soleil, ou lors de la première exécution pendant l'installation de l'intégration.
- Les données de prévision sont toujours demandées toutes les heures entre le lever et le coucher du soleil, et une fois à minuit chaque jour. *Supprimez simplement l'ancien capteur de compteur API, car il n'est plus utilisé.*

v3.0.5 bêta

- Valeurs des capteurs « cette heure » et « l'heure suivante » corrigées.
- Ralentir l'interrogation de l'API s'il y a plus d'un toit à interroger.
- Corriger les données du graphique de la première heure.
- Peut-être RC1 ? À voir.

v3.0.4 bêta

- Corrections de bugs.

v3.0

- réécriture complète

Les données historiques antérieures ne sont pas disponibles.




## Crédits

Modifié à partir des grandes œuvres de

- oziee/ha-solcast-solar
- @rany2 - ranygh@riseup.net
- dannerph/homeassistant-solcast
- cjtapper/solcast-py
- bibliothèques home-assistant/prévision_solaire


