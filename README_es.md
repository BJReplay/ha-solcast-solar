# Integración de pronóstico solar fotovoltaico HA Solcast

<!--[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)-->

[](https://github.com/custom-components/hacs)![insignia hacs](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)![Lanzamiento de GitHub](https://img.shields.io/github/v/release/BJReplay/ha-solcast-solar?style=for-the-badge)[](https://github.com/BJReplay/ha-solcast-solar/releases/latest)![descargas de hacs](https://img.shields.io/github/downloads/BJReplay/ha-solcast-solar/latest/total?style=for-the-badge)![Licencia de GitHub](https://img.shields.io/github/license/BJReplay/ha-solcast-solar?style=for-the-badge)![Actividad de confirmación de GitHub](https://img.shields.io/github/commit-activity/y/BJReplay/ha-solcast-solar?style=for-the-badge)![Mantenimiento](https://img.shields.io/maintenance/yes/2026?style=for-the-badge)

**Idiomas:** [🇦🇺 Inglés](https://github.com/BJReplay/ha-solcast-solar/blob/main/README.md) | [🇩🇪 Alemán](https://github.com/BJReplay/ha-solcast-solar/blob/main/README_de.md) | [🇫🇷 Francés](https://github.com/BJReplay/ha-solcast-solar/blob/main/README_fr.md)

## Preámbulo

Este componente personalizado integra el pronóstico fotovoltaico Solcast para aficionados en Home Assistant (https://www.home-assistant.io).

Permite la visualización del pronóstico solar en el tablero de energía y admite la amortiguación flexible del pronóstico, la aplicación de un límite estricto para sistemas fotovoltaicos de gran tamaño, un conjunto integral de sensores y entidades de configuración, junto con atributos de sensores que contienen detalles completos del pronóstico para respaldar la automatización y la visualización.

Es una integración madura con una comunidad activa y desarrolladores receptivos.

Esta integración no es creada, mantenida, respaldada ni aprobada por Solcast.

> [!TIP]
>
> #### Instrucciones de soporte
>
> Consulte las [preguntas frecuentes](https://github.com/BJReplay/ha-solcast-solar/blob/main/FAQ.md) para conocer los problemas y soluciones más comunes, revise las [discusiones](https://github.com/BJReplay/ha-solcast-solar/discussions) fijadas y activas y revise los [problemas](https://github.com/BJReplay/ha-solcast-solar/issues) abiertos antes de crear un nuevo problema o discusión.
>
> No publiques comentarios similares sobre problemas existentes (pero no dudes en dar "me gusta" o suscribirte a las notificaciones sobre problemas similares) ni asumas que, si tienes un error similar, es el mismo. A menos que el error sea idéntico, probablemente no sea el mismo.
>
> Considere siempre si debe informar un error en la integración o si necesita ayuda para configurarla. Si necesita ayuda, consulte si existe una discusión con la respuesta a su pregunta o formule una pregunta en la sección de discusión.
>
> Si cree que ha encontrado un problema que es un error, asegúrese de seguir las instrucciones de la plantilla de problema al plantear su problema.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

> [!NOTE]
>
> Esta integración puede reemplazar la antigua integración oziee/ha-solcast-solar, que ya no se desarrolla y ha sido eliminada. Desinstalar la versión de Oziee e instalar esta, o simplemente descargarla sobre la anterior, conservará todo el historial y la configuración. Si **desinstaló** la integración de Oziee e instaló esta, deberá volver a seleccionar Solcast Solar como fuente de producción de pronóstico para su panel de energía.

# Tabla de contenido

1. [Conceptos clave de integración de Solcast](#key-solcast-integration-concepts)
2. [Requisitos de Solcast](#solcast-requirements)
3. [Instalación](#installation)
    1. [HACS recomendado](#hacs-recommended)
    2. [Instalación manual en HACS](#installing-manually-in-hacs)
    3. [Instalación manual (sin usar HACS)](#installing-manually-(not-using-hacs))
    4. [Versiones beta](#beta-versions)
4. [Configuración](#configuration)
    1. [Actualización de previsiones](#updating-forecasts)
        1. [Actualización automática de previsiones](#auto-update-of-forecasts)
        2. [Uso de una automatización de alta disponibilidad para actualizar pronósticos](#using-an-ha-automation-to-update-forecasts)
    2. [Configurar los ajustes del panel de energía de HA](#set-up-ha-energy-dashboard-settings)
5. [Interactuando](#interacting)
    1. [Sensores](#sensors)
    2. [Atributos](#attributes)
    3. [Comportamiento](#actions)
    4. [Configuración](#configuration)
    5. [Diagnóstico](#diagnostic)
6. [Configuración avanzada](#advanced-configuration)
    1. [Configuración de amortiguación](#dampening-configuration)
        1. [Amortiguación automatizada](#automated-dampening)
        2. [Amortiguación horaria simple](#simple-hourly-dampening)
        3. [Amortiguación granular](#granular-dampening)
        4. [Lectura de valores de pronóstico en una automatización](#reading-forecast-values-in-an-automation)
        5. [Lectura de valores de amortiguación](#reading-dampening-values)
    2. [Configuración de los atributos del sensor](#sensor-attributes-configuration)
    3. [Configuración de límite duro](#hard-limit-configuration)
    4. [Configuración de sitios excluidos](#excluded-sites-configuration)
    5. [Opciones de configuración avanzadas](#advanced-configuration-options)
7. [Sensores de plantilla de muestra](#sample-template-sensors)
8. [Ejemplo de gráfico de Apex para el panel de control](#sample-apex-chart-for-dashboard)
9. [Problemas conocidos](#known-issues)
10. [Solución de problemas](#troubleshooting)
11. [Eliminación completa de la integración](#complete-integration-removal)
12. [Cambios](#Changes)

## Conceptos clave de integración de Solcast

El servicio Solcast genera un pronóstico de la generación solar fotovoltaica desde hoy hasta el final de un máximo de trece días. Esto supone un total de catorce días. Los primeros siete pronósticos diarios se muestran mediante un sensor independiente, y el valor corresponde a la generación solar total prevista para cada día. Los días pronosticados posteriores no se muestran mediante sensores, pero se pueden visualizar en el panel de Energía.

También hay disponibles sensores separados que contienen la potencia de generación máxima esperada, el tiempo de generación máxima y varios pronósticos para la próxima hora, 30 minutos y más.

Si existen varios paneles en diferentes orientaciones de tejado, estos pueden configurarse en su cuenta de Solcast como "sitios de tejado" independientes con diferentes azimuts, inclinaciones y generación de picos, hasta un máximo de dos sitios para una cuenta gratuita de aficionado. Estos pronósticos de sitios independientes se combinan para formar los valores de los sensores de integración y los datos de pronóstico del panel de energía.

Solcast produce tres estimaciones de generación solar para cada período de media hora de todos los días pronosticados.

- El pronóstico 'central' o del 50% o con mayor probabilidad de ocurrencia se expone como la `estimate` mediante la integración.
- Pronóstico del '10%' o 1 en 10 'peor de los casos' suponiendo una mayor cobertura de nubes de lo esperado, expuesto como `estimate10` .
- Pronóstico del '90%' o 1 en 10 'mejor caso' asumiendo una cobertura de nubes menor a la esperada, expuesto como `estimate90` .

El detalle de estas diferentes estimaciones de pronóstico se puede encontrar en los atributos del sensor, que contienen intervalos diarios de 30 minutos e intervalos horarios calculados a lo largo del día. Los atributos independientes suman las estimaciones disponibles o las desglosan por sitio Solcast. (Esta integración suele hacer referencia a un sitio Solcast por su "ID de recurso del sitio", que se puede encontrar en el sitio Solcast: https://toolkit.solcast.com.au/)

El panel de energía de Home Assistant se completa con datos históricos proporcionados por la integración, que se conservan hasta dos años. (El historial de pronósticos no se almacena como estadísticas de Home Assistant, sino en un archivo de caché `json` que mantiene la integración). El historial mostrado puede incluir pronósticos anteriores o datos "reales estimados", seleccionables como opción de configuración.

Es posible manipular los valores pronosticados para tener en cuenta el sombreado predecible en ciertos momentos del día, ya sea automáticamente o mediante el establecimiento de factores de atenuación para períodos de una o media hora. También se puede establecer un límite estricto para paneles solares de gran tamaño, donde la generación esperada no puede superar la capacidad máxima del inversor. Estos dos mecanismos son las únicas maneras de manipular los datos de pronóstico de Solcast.

Solcast también produce datos reales estimados históricos. Esto suele ser más preciso que un pronóstico, ya que se utilizan imágenes satelitales de alta resolución, observaciones meteorológicas y otras observaciones climáticas (como vapor de agua y smog) para calcular las estimaciones. La función de integración de amortiguamiento automático puede utilizar los datos reales estimados y compararlos con el historial de generación para generar un modelo de generación proyectada reducida que tenga en cuenta el sombreado local. Los datos reales estimados también se pueden visualizar en el panel de Energía, independientemente de si se utiliza o no el amortiguamiento automático.

> [!NOTE]
>
> Solcast ha modificado sus límites de API. Los nuevos usuarios aficionados pueden realizar un máximo de 10 llamadas a la API al día. Los usuarios aficionados originales conservarán hasta 50 llamadas al día.

## Requisitos de Solcast

Regístrese para obtener una clave API (https://solcast.com/).

> Solcast puede tardar hasta 24 horas en crear la cuenta.

Configure correctamente sus sitios en la azotea en `solcast.com` .

Elimine todos los sitios de muestra de su panel de Solcast (consulte [Problemas conocidos](#known-issues) para ver ejemplos de sitios de muestra y el problema que podría ocurrir si no los elimina).

Copie la clave API para usarla con esta integración (consulte [Configuración](#Configuration) a continuación).

Tenga en cuenta la importancia de configurar correctamente su sitio Solcast. Utilice la indicación "El sitio está orientado" para asegurarse de que el azimut esté correctamente indicado, ya que si es incorrecto, los pronósticos aparecerán desfasados, posiblemente hasta una hora durante el día.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_tilt.png" width="600">

El azimut *no* se establece en un valor de 0 a 359 grados, sino en un valor de 0 a 180 para orientación oeste, o de 0 *a* -179 para orientación este. Este valor representa los grados de ángulo con respecto al norte, ya sea el oeste o el este. Si no está seguro, investigue rápidamente.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth.png" width="300">

Un método tradicional que puede funcionar es obtener una imagen satelital de Google Maps de tu casa orientada al norte y medir el acimut con un transportador de plástico de 180 grados, con la regla alineada de norte a sur en la pantalla y el punto central en el lateral de un panel representativo. Cuenta los grados con respecto al norte. Para orientarte hacia el oeste o el este, gira el transportador. Quizás necesites convertir la imagen de Maps a formato PNG/JPG y añadir extensiones de línea a la orientación para poder medir el ángulo con precisión.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/azimuth_house.png" width="300">

Utilizar Google Earth o ChatGPT son otras alternativas.

> [!NOTE]
>
> Solcast tiene su sede en Sídney, Australia, en el hemisferio sur, y utiliza la numeración de azimut en grados que apuntan en dirección contraria al norte. Si vive en el hemisferio norte, es probable que cualquier servicio de mapas en línea que permita determinar el azimut utilice una convención de numeración en grados que apuntan en dirección contraria al *sur* , lo que generará valores incompatibles.
>
> Se considera que una configuración Solcast del techo alineado al Norte/Noreste/Noroeste en el hemisferio norte o al Sur/Sureste/Suroeste en el hemisferio sur es posiblemente inusual porque estas orientaciones no miran directamente al sol en ningún momento.
>
> Al iniciarse, la integración validará la configuración de azimut de Solcast para detectar posibles errores de configuración. Además, emitirá un mensaje de advertencia en el registro de Home Assistant y notificará un problema si detecta una alineación inusual del techo. Si recibe esta advertencia y ha confirmado que la configuración de Solcast es correcta, puede ignorarla. La advertencia sirve para detectar errores de configuración.
>
> Siempre hay instalaciones atípicas, como dos tejados orientados al oeste y al este con paneles instalados en ambas caras, separados 180 grados entre sí. Un tejado se considerará "inusual". Compruebe el azimut según Solcast y corrija o ignore la advertencia según corresponda. Recuerde que 0° = NORTE según Solcast, y las orientaciones son relativas a este valor.

## Instalación

### HACS recomendado

*(Método de instalación recomendado)*

Instalar como repositorio predeterminado usando HACS. Encontrarás más información sobre HACS [aquí](https://hacs.xyz/) . Si aún no has instalado HACS, ¡hazlo primero!

La forma más sencilla de instalar la integración es hacer clic en el botón a continuación para abrir esta página en su página HACS de Home Assistant (se le solicitará la URL de su Home Assistant si nunca ha usado este tipo de botón antes).

[](https://my.home-assistant.io/redirect/hacs_repository/?owner=BJReplay&repository=ha-solcast-solar&category=integration)![Abra su instancia de Home Assistant y abra un repositorio dentro de la Tienda de la Comunidad de Home Assistant.](https://my.home-assistant.io/badges/hacs_repository.svg)

Se le pedirá que confirme que desea abrir el repositorio dentro de HACS dentro de Home Assistant:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png">

Verás esta página, con un botón `↓ Download` cerca de la parte inferior derecha: haz clic en él:

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png">

Se le solicitará que descargue el componente Solcast PV Forecast: haga clic en `Download` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png">

Una vez instalado, probablemente notarás una notificación emergente en `Settings` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png">

Haga clic en configuración y debería ver una notificación de reparación cuando `Restart required` :

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png">

Si no lo ve (quizás esté usando una versión anterior de Home Assistant), vaya a `System` , `Settings` , haga clic en el icono de encendido y, a `Restart Home Assistant` . Debe reiniciar Home Assistant para poder configurar el componente personalizado Solcast PV Forecast que acaba de descargar.

Una vez que haya reiniciado, siga en [Configuración](#configuration) para continuar configurando el componente de integración Solcast PV Forecast.

### Instalación manual en HACS

Más información [aquí](https://hacs.xyz/docs/faq/custom_repositories/)

1. (Si lo usa, elimine oziee/ha-solcast-solar en HACS)
2. Agregue un repositorio personalizado (menú de tres puntos verticales, arriba a la derecha) `https://github.com/BJReplay/ha-solcast-solar` como `integration`
3. Busque 'Solcast' en HACS, ábralo y haga clic en el botón `Download`
4. Ver [configuración](#configuration) a continuación

Si anteriormente utilizó ha-solcast-solar de Oziee, entonces todo el historial y la configuración deberían permanecer.

### Instalación manual (sin usar HACS)

¡Probablemente **no** quieras hacer esto! Usa el método HACS mencionado anteriormente a menos que sepas lo que haces y tengas una buena razón para instalarlo manualmente.

1. Usando la herramienta de su elección, abra la carpeta (directorio) para su configuración de HA (donde encontrará `configuration.yaml` )
2. Si no tiene una carpeta `custom_components` allí, debe crearla
3. En la carpeta `custom_components` crea una nueva carpeta llamada `solcast_solar`
4. Descargue *todos* los archivos de la carpeta `custom_components/solcast_solar/` en este repositorio
5. Coloca los archivos que descargaste en la nueva carpeta que creaste
6. *Reinicie HA para cargar la nueva integración*
7. Ver [configuración](#configuration) a continuación

### Versiones beta

Es posible que haya versiones beta disponibles que solucionen los problemas.

Consulta https://github.com/BJReplay/ha-solcast-solar/releases para ver si ya se ha resuelto algún problema. De ser así, activa la entidad `Solcast PV Pre-release` para habilitar la actualización beta (o, para HACS v1, activa `Show beta versions` al volver a descargar).

Sus comentarios sobre las versiones beta de prueba son muy bienvenidos en las [discusiones](https://github.com/BJReplay/ha-solcast-solar/discussions) del repositorio, donde existirá una discusión para cualquier versión beta activa.

## Configuración

1. [Haga clic aquí](https://my.home-assistant.io/redirect/config_flow_start/?domain=solcast_solar) para agregar directamente una integración `Solcast Solar` **o**<br> a. En Home Assistant, vaya a Configuración -&gt; [Integraciones](https://my.home-assistant.io/redirect/integrations/)<br> b. Haga clic en `+ Add Integrations`

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png">

y comience a escribir `Solcast PV Forecast` para que aparezca la integración de Solcast PV Forecast y selecciónela.<br>

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png">

1. Ingresa tu `Solcast API Key` , `API limit` , opción de actualización automática deseada y haz clic en `Submit` . Si tienes más de una cuenta de Solcast porque tienes más de dos configuraciones de azotea, ingresa todas las claves de API de las cuentas de Solcast separadas por una coma `xxxxxxxx-xxxxx-xxxx,yyyyyyyy-yyyyy-yyyy` . ( *Nota: Esto puede infringir los términos y condiciones de Solcast si tienes más de una cuenta si las ubicaciones de estos sitios de cuenta están a menos de un kilómetro entre sí, o 0,62 millas).* Tu límite de API será 10 para nuevos usuarios de Solcast o 50 para los primeros usuarios. Si el límite de API es el mismo para varias cuentas, ingresa un solo valor para ese, o ambos valores separados por una coma, o el límite de API más bajo de todas las cuentas como un solo valor. Consulta [la configuración de sitios excluidos](#excluded-sites-configuration) para un caso de uso de claves de API múltiples.
2. Si no se eligió una opción de actualización automática, cree su propia automatización para llamar a la acción `solcast_solar.update_forecasts` en los momentos en que desee actualizar el pronóstico solar.
3. Configure los ajustes del panel de energía de Home Assistant.
4. Para cambiar otras opciones de configuración después de la instalación, seleccione la integración en `Devices & Services` y luego `CONFIGURE` .

Asegúrate de usar tu `API Key` y no el ID de la azotea creado en Solcast. Puedes encontrar tu clave API aquí: [api key](https://toolkit.solcast.com.au/account) .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png" width="500">

> [!IMPORTANT] The API key and associated sites will be checked when the initial configuration is saved. It is possible for this initial check to fail because the Solcast API is temporarily unavailable, and if it is then simply retry configuration after some minutes. The configure error message will indicate if this is the case.

### Actualización de previsiones

Todos los sitios deben actualizarse en el mismo momento mediante la integración, por lo que un límite de clave API diferente utilizará el límite más bajo de todas las claves configuradas.

> [!NOTE]
>
> La razón para usar el límite mínimo es simple, y una solución alternativa es problemática: los valores pronosticados para cada intervalo de treinta minutos se combinan para formar el pronóstico general, por lo que todos los sitios deben estar representados para todos los intervalos. (Puede pensar que la "interpolación" de otros intervalos de sitio podría ser una opción, pero recuerde que esto es un pronóstico. Se considerarán las solicitudes de extracción siempre que vayan acompañadas de escenarios `pytest` completos).

#### Actualización automática de previsiones

El valor predeterminado para las nuevas instalaciones es la actualización automática del pronóstico programado.

Al usar la actualización automática, se obtendrán actualizaciones del pronóstico que se distribuyen automáticamente durante las horas de sol o, alternativamente, durante un período de 24 horas. Calcula el número de actualizaciones diarias según la cantidad de sitios de azotea de Solcast y el límite de API configurado, o el menor número posible de actualizaciones para todos los sitios si se utilizan varias claves API.

Si se desea obtener una actualización fuera de este horario, se puede reducir el límite de la API en la configuración de la integración y configurar una automatización para ejecutar la acción `solcast_solar.force_update_forecasts` a la hora deseada. (Tenga en cuenta que si la actualización automática está habilitada, se rechazará la ejecución de la acción `solcast_solar.update_forecasts` ; por lo tanto, utilice la opción "Forzar actualización").

Por ejemplo, para actualizar justo después de medianoche y aprovechar la actualización automática, cree la automatización deseada para forzar la actualización y luego reduzca el límite de API configurado en la automatización según corresponda. (En este ejemplo, si la clave de API permite un total de diez llamadas al día y dos sitios en la azotea, reduzca el límite de API a ocho, ya que se utilizarán dos actualizaciones al ejecutar la automatización).

El uso de la actualización forzada no incrementará el contador de uso de la API, lo cual es así por diseño.

> [!NOTE] *Transitioning to auto-update from using an automation:*
>
> Si actualmente utiliza la automatización recomendada, que distribuye las actualizaciones de forma bastante uniforme entre el amanecer y el anochecer, activar la actualización automática entre el amanecer y el anochecer no debería causar fallos inesperados en la obtención del pronóstico debido al agotamiento del límite de la API. La automatización recomendada no es idéntica a la actualización automática, pero su sincronización es bastante similar.
>
> Si se implementa un límite de API reducido, además de una actualización forzada a una hora diferente (como medianoche), podría requerirse un ajuste de 24 horas, lo que podría provocar que se informe sobre el agotamiento de la API, incluso si el recuento de uso de la API de Solcast no se ha agotado. Estos errores se solucionarán en 24 horas.

#### Uso de una automatización de alta disponibilidad para actualizar pronósticos

Si la actualización automática no está habilitada, cree una o varias automatizaciones y configure los tiempos de activación que prefiera para sondear los nuevos datos de pronóstico de Solcast. Utilice la acción `solcast_solar.update_forecasts` . Se proporcionan ejemplos, así que modifíquelos o cree los suyos propios según sus necesidades.

<details><summary><i>Haga clic aquí para ver los ejemplos</i><p></p></summary>
</details>

Para aprovechar al máximo las llamadas API disponibles por día, puede hacer que la automatización llame a la API utilizando un intervalo calculado por la cantidad de horas del día dividida por la cantidad total de llamadas API que puede realizar por día.

Esta automatización basa los tiempos de ejecución en el amanecer y el atardecer, que varían según el mundo, por lo que distribuye la carga en Solcast. Es muy similar al comportamiento de la actualización automática del amanecer al atardecer, con la diferencia de que también incorpora un desfase horario aleatorio, lo que, con suerte, evitará que los servidores de Solcast se saturen con varias llamadas simultáneas.

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
> Si tiene dos matrices en su techo, se realizarán dos llamadas a la API por cada actualización, lo que reduce el número de actualizaciones a cinco al día. En este caso, cambie a: `api_request_limit = 5`

La siguiente automatización también incluye una aleatorización para que las llamadas no se realicen exactamente al mismo tiempo, con lo que se espera evitar la posibilidad de que los servidores de Solcast se inunden con múltiples llamadas al mismo tiempo, pero se activa cada cuatro horas entre el amanecer y el atardecer:

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

La próxima automatización se activa a las 4 a. m., a las 10 a. m. y a las 4 p. m., con un retraso aleatorio.

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
> Los servidores Solcast parecen estar ocasionalmente sobrecargados y devuelven códigos de error 429/Demasiado ocupado. La integración se pausará automáticamente y reintentará la conexión varias veces, pero en ocasiones incluso esta estrategia puede fallar al descargar los datos del pronóstico.
>
> Cambiar tu clave API no es la solución, ni tampoco desinstalar y reinstalar la integración. Estos "trucos" pueden parecer eficaces, pero lo único que ha ocurrido es que lo has vuelto a intentar más tarde y la integración ha funcionado, ya que los servidores de Solcast tienen menos carga.
>
> Para saber si este es tu problema, consulta los registros de Home Assistant. Para obtener información detallada (necesaria al informar un problema), asegúrate de tener activado el registro de depuración.
>
> Las instrucciones de captura de registros se encuentran en la Plantilla de problema de error: las verá si comienza a crear un nuevo problema; asegúrese de incluir estos registros si desea la ayuda de los contribuyentes del repositorio.
>
> A continuación se muestra un ejemplo de mensajes de ocupación y un reintento exitoso (con el registro de depuración habilitado). En este caso, no hay problema, ya que el reintento es exitoso. Si fallan diez intentos consecutivos, la recuperación del pronóstico finalizará con un `ERROR` . En ese caso, active manualmente otra acción `solcast_solar.update_forecasts` (o, si la actualización automática está habilitada, utilice `solcast_solar.force_update_forecasts` ) o espere a la siguiente actualización programada.
>
> Si la carga de datos de los sitios al iniciar la integración es la llamada que falló con el error 429/Demasiado ocupado, la integración se iniciará si los sitios se almacenaron previamente en caché y utilizará esta información de forma ciega. Si se han realizado cambios en los sitios, estos no se leerán, lo que podría generar resultados inesperados. Si se produce algún imprevisto, revise el registro. Siempre revise el registro si ocurre algún imprevisto; al reiniciar, es probable que los sitios actualizados se lean correctamente.

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

### Configurar los ajustes del panel de energía de HA

Vaya a `Settings` , `Dashboards` , `Energy` y haga clic en el ícono del Lápiz para editar la configuración de su panel de Energía.

El pronóstico solar debe estar asociado a un elemento de generación solar en su panel de energía.

Edita un elemento `Solar production` `Solar Panels` que hayas creado previamente (o que vayas a crear ahora). No añadas un elemento `Solar production` aparte, ya que la situación se complicará.

Solo puede haber una única configuración del pronóstico total de PV de Solcast en el panel de energía que cubra todos los sitios (conjuntos) en su cuenta de Solcast, no es posible dividir el pronóstico en el panel de energía para diferentes conjuntos solares/sitios de Solcast.

> [!IMPORTANT]
>  If you do not have a solar generation sensor in your system then this integration will not work in the Energy dashboard. The graph and adding the forecast integration rely on there being a solar generation sensor set up.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png" width="500">

En la sección `Solar production forecast` , seleccione `Forecast Production` y luego seleccione la opción `Solcast Solar` . Haga clic en `Save` y Home Assistant se encargará del resto.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">

## Interactuando

Hay muchas acciones, sensores y elementos de configuración expuestos por la integración, junto con muchos atributos de sensores que pueden habilitarse.

Utilice las `Developer tools` de Home Assistant para examinar los atributos expuestos, ya que su nomenclatura depende principalmente de la implementación. Consulte ejemplos en otras secciones de este archivo Léame para comprender cómo se pueden usar.

También hay una colección de plantillas Jinja2 disponible en https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md que contiene ejemplos de plantillas básicas, intermedias y avanzadas.

### Sensores

Todos los nombres de sensores están precedidos por el nombre de integración `Solcast PV Forecast` .

Nombre | Tipo | Atributos | Unidad | Descripción
--- | --- | --- | --- | ---
`Forecast Today` | número | Y | `kWh` | Producción solar total prevista para hoy.
`Forecast Tomorrow` | número | Y | `kWh` | Producción solar total prevista para el día + 1 (mañana).
`Forecast Day 3` | número | Y | `kWh` | Producción solar total prevista para el día + 2 (día 3, deshabilitado por defecto).
`Forecast Day 4` | número | Y | `kWh` | Producción solar total prevista para el día + 3 (día 4, deshabilitado por defecto).
`Forecast Day 5` | número | Y | `kWh` | Producción solar total prevista para el día + 4 (día 5, deshabilitado por defecto).
`Forecast Day 6` | número | Y | `kWh` | Producción solar total prevista para el día + 5 (día 6, deshabilitado por defecto).
`Forecast Day 7` | número | Y | `kWh` | Producción solar total prevista para el día + 6 (día 7, deshabilitado por defecto).
`Forecast This Hour` | número | Y | `Wh` | Producción solar prevista para la hora actual (los atributos contienen un desglose del sitio).
`Forecast Next Hour` | número | Y | `Wh` | Producción solar prevista para la próxima hora (los atributos contienen desglose del sitio).
`Forecast Next X Hours` | número | Y | `Wh` | Producción solar prevista personalizada y definida por el usuario para las próximas X horas, deshabilitada de forma predeterminada<br> Nota: Este pronóstico comienza en la hora actual, no está alineado con la hora como "Esta hora", "Próxima hora".
`Forecast Remaining Today` | número | Y | `kWh` | Producción solar restante prevista para hoy.
`Peak Forecast Today` | número | Y | `W` | Mayor producción prevista dentro de un período de una hora hoy (los atributos contienen un desglose del sitio).
`Peak Time Today` | fecha/hora | Y |  | Hora de máxima producción solar prevista para hoy (los atributos contienen desglose del sitio).
`Peak Forecast Tomorrow` | número | Y | `W` | Mayor producción prevista dentro de un período de una hora mañana (los atributos contienen un desglose del sitio).
`Peak Time Tomorrow` | fecha/hora | Y |  | Hora de máxima producción solar prevista para mañana (los atributos contienen desglose del sitio).
`Forecast Power Now` | número | Y | `W` | Potencia solar nominal prevista para este momento (los atributos contienen el desglose del sitio).
`Forecast Power in 30 Minutes` | número | Y | `W` | Energía solar nominal prevista en 30 minutos (los atributos contienen un desglose del sitio).
`Forecast Power in 1 Hour` | número | Y | `W` | Energía solar nominal prevista en 1 hora (los atributos contienen un desglose del sitio).

> [!NOTE]
>
> Cuando un desglose del sitio está disponible como atributo, el nombre del atributo es el ID del recurso del sitio Solcast (con guiones reemplazados por guiones bajos).
>
> La mayoría de los sensores también incluyen un atributo para `estimate` , `estimate10` y `estimate90` . Se pueden crear sensores de plantilla para exponer su valor, o bien, se puede usar `state_attr()` directamente en las automatizaciones.
>
> Acceda a estos en un sensor de plantilla o automatización usando algo como:
>
> ```
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', '1234_5678_9012_3456') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10_1234_5678_9012_3456') | float(0) }}
> ```
>
> Consulte también el gráfico PV de muestra a continuación para saber cómo graficar los detalles del pronóstico a partir del atributo detailedForecast.

> [!NOTE]
>
> Los valores para `Next Hour` y `Forecast Next X Hours` pueden ser diferentes si la configuración personalizada de X horas es 1. Esto tiene una explicación simple.
>
> Se calculan con diferentes horas de inicio y fin. Una corresponde al inicio de esta hora, es decir, en el pasado, p. ej., de 14:00:00 a 15:00:00. El sensor personalizado corresponde a un período de cinco minutos, p. ej., de 14:20:00 a 15:20:00, utilizando valores interpolados.
>
> Es probable que esto genere un resultado diferente según la hora en que se solicite el valor, por lo que no es incorrecto. Simplemente es diferente.

### Atributos

Como se mencionó anteriormente, los atributos de los sensores se crean para permitir el uso de variaciones de estado en las plantillas. Algunos ejemplos son la confianza de la estimación, `estimate10` / `estimate` / `estimate90` . El *estado* del sensor generalmente se mantiene en el valor predeterminado de `estimate` , pero se puede desear mostrar el décimo percentil de un sensor en un panel, lo cual se habilita mediante el uso de valores *de atributo* .

Algunos nombres de atributos son específicos de la implementación (aquí se ofrecen ejemplos), y otros están deshabilitados por defecto o por preferencia del usuario para simplificar la configuración. Estas preferencias se configuran en el cuadro de diálogo `CONFIGURE` .

Los nombres de los atributos no deben contener guiones. Los ID de recursos del sitio Solcast *se* nombran con guiones, por lo que, cuando un atributo se nombra con el ID de recurso del sitio que representa, los guiones se reemplazan por guiones bajos.

Todos los sensores de pronóstico detallados que brindan desgloses por hora o media hora brindan (al igual que los datos Solcast subyacentes) datos en kW: estos son sensores de potencia, no sensores de energía, y representan el pronóstico de potencia promedio para el período.

Para todos los sensores:

- `estimate10` : valor de pronóstico del percentil 10 (número)
- `estimate` : valor de pronóstico del percentil 50 (número)
- `estimate90` : valor de pronóstico del percentil 90 (número)
- `1234_5678_9012_3456` : Un valor de sitio individual, es decir, una parte del total (número)
- `estimate10_1234_5678_9012_3456` : 10.º para un valor de sitio individual (número)
- `estimate_1234_5678_9012_3456` : 50.º para un valor de sitio individual (número)
- `estimate90_1234_5678_9012_3456` : 90.º para un valor de sitio individual (número)

Solo para el sensor `Forecast Next X Hours` :

- `custom_hours` : El número de horas informadas por el sensor (número)

Solo para sensores de pronóstico diario:

- `detailedForecast` : Un desglose cada media hora de la generación de energía promedio esperada para cada intervalo (lista de diccionarios, unidades en kW, no kWh) y, si la amortiguación automática está activa, también se incluye el factor determinado para cada intervalo.
- `detailedHourly` : un desglose horario de la generación de energía promedio esperada para cada intervalo (lista de diccionarios, unidades en kW)
- `detailedForecast_1234_5678_9012_3456` : Desglose de la generación de energía promedio esperada para cada intervalo, específico del sitio, cada media hora (lista de diccionarios, unidades en kW)
- `detailedHourly_1234_5678_9012_3456` : Un desglose horario específico del sitio de la generación de energía promedio esperada para cada intervalo (lista de diccionarios, unidades en kW)

La "lista de diccionarios" tiene el siguiente formato, con valores de ejemplo utilizados: (Note la inconsistencia en `pv_estimateXX` vs. `estimateXX` usado en otros lugares. La historia es la culpable).

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

### Comportamiento

Acción | Descripción
--- | ---
`solcast_solar.update_forecasts` | Actualizar los datos de pronóstico (rechazado si la actualización automática está habilitada).
`solcast_solar.force_update_forecasts` | Forzar la actualización de los datos de pronóstico (realiza una actualización independientemente del seguimiento del uso de la API o la configuración de actualización automática, y no incrementa el contador de uso de la API; se rechaza si la actualización automática no está habilitada).
`solcast_solar.force_update_estimates` | Forzar la actualización de los datos reales estimados (no incrementa el contador de uso de API, se rechaza si la obtención de datos reales estimados no está habilitada).
`solcast_solar.clear_all_solcast_data` | Elimina los datos almacenados en caché e inicia una búsqueda inmediata de nuevos valores pasados reales y previstos.
`solcast_solar.query_forecast_data` | Devuelve una lista de datos de pronóstico utilizando un rango de fecha y hora de inicio a fin.
`solcast_solar.query_estimate_data` | Devuelve una lista de datos reales estimados utilizando un rango de fecha y hora de inicio a fin.
`solcast_solar.set_dampening` | Actualice los factores de amortiguación.
`solcast_solar.get_dampening` | Obtenga los factores de amortiguación configurados actualmente.
`solcast_solar.set_hard_limit` | Establecer límite estricto de previsión del inversor.
`solcast_solar.remove_hard_limit` | Eliminar el límite estricto de previsión del inversor.

Aquí se proporcionan parámetros de ejemplo para cada acción `query` , `set` y `get` . Utilice `Developer tools` | `Actions` para mostrar los parámetros disponibles para cada una con una descripción.

Cuando se necesita un parámetro 'sitio', utilice el ID del recurso del sitio Solcast y no el nombre del sitio.

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

### Configuración

Nombre | Tipo | Descripción
--- | --- | ---
`Forecast Field` | selector | Seleccione la confianza del pronóstico utilizada para los estados del sensor como 'estimación', 'estimación10' o 'estimación90'.

### Diagnóstico

Todos los nombres de los sensores de diagnóstico están precedidos por `Solcast PV Forecast` excepto `Rooftop site name` .

Nombre | Tipo | Atributos | Unidad | Descripción
--- | --- | --- | --- | ---
`API Last Polled` | fecha/hora | Y | `datetime` | Fecha y hora en que se actualizó correctamente el pronóstico por última vez.
`API Limit` | número | norte | `integer` | Total de veces que se puede llamar a la API en un período de 24 horas[^1].
`API used` | número | norte | `integer` | Total de veces que se llamó a la API hoy (el contador de API se reinicia a cero a la medianoche UTC)[^1].
`Dampening` | booleano | Y | `bool` | Si la amortiguación está habilitada (deshabilitada de manera predeterminada).
`Hard Limit Set` | número | norte | `float` o `bool` | `False` si no se establece, de lo contrario valor en `kilowatts` .
`Hard Limit Set ******AaBbCc` | número | norte | `float` | Límite máximo de la cuenta individual. Valor en `kilowatts` .
`Rooftop site name` | número | Y | `kWh` | Pronóstico total para la azotea hoy (los atributos contienen la configuración del sitio)[^2].

Los atributos `API Last Polled` incluyen lo siguiente:

- `failure_count_today` : el recuento de fallas (como `429/Too busy` ) que han ocurrido desde la medianoche, hora local.
- `failure_count_7_day` : El recuento de fallas que han ocurrido durante los últimos siete días.
- `last_attempt` : Fecha y hora del último intento de actualización del pronóstico. Se considera "actualmente sano" si el último sondeo es posterior al último intento.

Si la actualización automática está habilitada, la última encuesta también presenta estos atributos:

- `auto_update_divisions` : la cantidad de actualizaciones automáticas configuradas para cada día.
- `auto_update_queue` : un máximo de 48 actualizaciones automáticas futuras actualmente en la cola.
- `next_auto_update` : la fecha y hora de la próxima actualización automática programada.

Si la amortiguación está activa, el sensor de amortiguación también presenta estos atributos:

- `integration_automated` : Booleano. Indica si la amortiguación automática está habilitada.
- `last_updated` : Fecha y hora. Fecha y hora en que se configuraron por última vez los factores de amortiguación.
- `factors` : Dict. El `interval` de inicio hora:minuto y `factor` como un número de punto flotante.

Ejemplo de atributos del sensor de amortiguación:

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

Los atributos `Rooftop site name` incluyen:

- `azimuth` / `tilt` : Orientación del panel.
- `capacity` : Capacidad del sitio en potencia CA.
- `capacity_dc` : Capacidad del sitio en energía CC.
- `install_date` : Fecha de instalación configurada.
- `loss_factor` : "factor de pérdida" configurado.
- `name` : el nombre del sitio configurado en solcast.com.
- `resource_id` : El ID del recurso del sitio.
- `tags` : Las etiquetas establecidas para el sitio de la azotea.

> [!NOTE]
>
> La latitud y la longitud no se incluyen intencionalmente en los atributos del sitio de la azotea por razones de privacidad.

[^1]: La información de uso de la API se rastrea internamente y puede no coincidir con el uso real de la cuenta.

[^2]: Cada azotea creada en Solcast aparecerá en una lista por separado.

## Configuración avanzada

### Configuración de amortiguación

Los valores de amortiguación tienen en cuenta el sombreado y ajustan la generación prevista. La amortiguación puede determinarse automáticamente o fuera de la integración y configurarse mediante una acción de servicio.

Cualquier cambio en los factores de amortiguación se aplicará a los pronósticos futuros (incluido el pronóstico del día actual). El historial de pronósticos conservará la amortiguación vigente en ese momento.

La amortiguación automática (descrita a continuación) calculará los factores de amortiguación generales para todos los sitios de azotea. Si se desea una amortiguación individual para cada sitio de azotea, se puede modelar en otro lugar con su propia solución de amortiguación y luego establecer los factores mediante la acción `solcast_solar.set_dampening` . Consulte la sección ["Amortiguación granular"](#granular-dampening) a continuación.

> [!NOTE]
>
> Cuando la amortiguación automática está habilitada, no será posible establecer factores de amortiguación por acción de servicio, ni manualmente en las opciones de integración, ni escribiendo el archivo `solcast-dampening.json` .
>
> (Si se intenta utilizar el método de escritura del archivo de amortiguación, se ignorará el contenido del nuevo archivo y luego se sobrescribirá con factores de amortiguación automáticos actualizados cuando se modelen).

#### Amortiguación automatizada

Una característica de la integración es la atenuación automática, que compara el historial de generación real con la generación anterior estimada para determinar la generación anómala regular. Esto resulta útil para identificar períodos de probable sombreado del panel y, posteriormente, aplicar automáticamente un factor de atenuación para los períodos previstos del día con probabilidad de sombreado, reduciendo así la energía prevista.

La amortiguación automatizada es dinámica y utiliza hasta catorce días consecutivos de generación y datos estimados de generación para construir su modelo y determinar los factores de amortiguación aplicables. No se utilizan más de catorce días. Al activar la función, cualquier límite en el historial posiblemente implicará un conjunto de datos reducido, pero este aumentará a catorce días con el tiempo y mejorará el modelado.

La amortiguación automatizada aplicará los mismos factores de amortiguación a todos los sitios de la azotea, según la generación de ubicación total y los datos de Solcast.

> [!NOTE]
>
> La amortiguación automática podría no serle útil, especialmente debido a la forma en que sus entidades generadoras reportan la energía, o si está en un plan de mercado energético mayorista donde los precios pueden ser negativos, por lo que limita la exportación del sitio en esos momentos. (Siga leyendo para conocer una posible solución en ese sentido).
>
> Esta función de amortiguación automática integrada será adecuada para muchas personas, pero no es una panacea.
>
> Puede parecer una opción de configuración sencilla, pero no lo es. Se trata de un código complejo que gestiona diferentes tipos de informes de generación fotovoltaica y posibles problemas de comunicación entre el inversor y Home Assistant, además de detectar la generación anómala causada por el sombreado.
>
> Si cree que la amortiguación automática no funciona correctamente, por favor, CONSIDERE, INVESTIGUE y luego INFORME cualquier problema, en ese orden. Incluya detalles de por qué cree que la amortiguación automática no funciona y la posible solución en cualquier informe de problemas.
>
> Si investiga y descubre que un problema se debe a su unidad de generación construida manualmente, es posible que la amortiguación automática no sea la solución adecuada. En ese caso, le recomendamos desarrollar su propia solución de amortiguación o ser técnicamente constructivo en cualquier mejora sugerida. Los componentes están disponibles para que usted construya su propio sistema utilizando amortiguación granular.
>
> Consulta también las "opciones avanzadas" para la integración. Hay muchas opciones avanzadas que se pueden configurar para la amortiguación automática, y estas podrían solucionar tu problema.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/automated-dampening.png" width="500">

La teoría de funcionamiento es sencilla: se basa en dos entradas clave y una tercera opcional.

##### Teoría del funcionamiento

La amortiguación automática genera primero un conjunto consistentemente óptimo de (más de un) período de generación [real estimado](https://github.com/BJReplay/ha-solcast-solar/issues/373#key-input-estimated-actual-data-from-solcast) cada media hora de los últimos catorce días. (Esto no corresponde a la generación real del sitio, sino a una estimación de Solcast de lo que debería haberse generado).

Luego, se compara con [el historial de generación](#key-input-actual-pv-generation-for-your-site) de estos períodos (excluyendo los períodos de generación en los que los límites de exportación podrían haberse visto afectados por [limitaciones opcionales](#optional-input-site-export-to-the-grid-combined-with-a-limit-value) o suprimidos intencionalmente). Se selecciona el valor de generación real más alto de entre los períodos reales similares mejor estimados, pero solo si hay más de un valor de generación. Este valor determina si es probable que factores externos afecten la generación y se utiliza para calcular un factor de amortiguamiento "base".

Dado que la amortiguación automática busca identificar cuándo el sombreado afecta la generación solar, descartará los intervalos diarios con una estimación de generación fotovoltaica inferior a la óptima. Estos intervalos corresponden a días en que la generación fotovoltaica se reduce debido a la nubosidad, la lluvia, etc.

Dicho de otro modo, y en un lenguaje muy sencillo, Solcast ha estimado anteriormente que la producción debería haber sido de X kW en promedio a una hora determinada en días soleados, pero el máximo alcanzado recientemente ha sido de Y kW, por lo que la integración ajustará las previsiones futuras hacia Y kW. O, incluso más simple, la generación real estimada es consistentemente superior a la que se puede alcanzar, por lo que se reduce la previsión.

Dado que los períodos de pronóstico varían con respecto a las mejores estimaciones debido a la nubosidad, el factor base se modifica antes de aplicarlo a los pronósticos mediante un cálculo de diferencia logarítmica. Si la generación solar pronosticada difiere significativamente de la mejor estimación utilizada para determinar el factor de amortiguamiento base, este se ajusta para que tenga un impacto mínimo (es decir, se acerque a un factor de 1,0). Esta determinación se basa en el valor de cada intervalo pronosticado, por lo que es probable que cada día tenga factores diferentes.

El ajuste del factor de amortiguamiento base se realiza porque una variación significativa en la generación pronosticada para un intervalo, en comparación con intervalos de generación anteriores con mejores resultados, indica que se espera un período de alta nubosidad. Esto adapta el amortiguamiento a los períodos nublados, donde la luz difusa es el componente más significativo de la generación solar, y no la luz solar directa, que es el componente más afectado por la sombra.

> [!TIP]
>
> Examine el atributo `detailedForecast` del pronóstico diario para ver los factores de amortiguación automáticos aplicados a cada intervalo. Se incluye un ejemplo de gráfico de Apex en [`TEMPLATES.md`](https://github.com/BJReplay/ha-solcast-solar/blob/main/TEMPLATES.md) para mostrar una aplicación práctica de esta información de amortiguación.

##### Entrada clave: Datos reales estimados de Solcast

Además de los pronósticos, el servicio Solcast también estima la generación real probable durante el día en cada azotea, basándose en imágenes satelitales de alta resolución, observaciones meteorológicas y la pureza del aire (vapor/smog). Estos datos se denominan "estimación real" y, por lo general, son bastante precisos para una ubicación determinada.

Obtener datos reales estimados requiere una llamada a la API, la cual consumirá la cuota de API para un usuario aficionado. Para ello, deberá considerar el consumo de llamadas a la API al aprovechar la amortiguación automática: una llamada por cada sitio de azotea Solcast configurado, por día y por clave de API. (Reduzca el límite de API para actualizaciones de pronóstico en las opciones en uno para un solo sitio de azotea, o en dos para dos sitios).

Los datos reales estimados pasados se adquieren justo después de la medianoche de cada día, hora local, y se actualizan aleatoriamente en 15 minutos. Si se habilita la amortiguación automática, los nuevos factores de amortiguación para el día siguiente se modelan inmediatamente después de la actualización de la estimación real. También es posible forzar una actualización de los valores reales estimados, lo que también intentará modelar los factores de amortiguación si corresponde.

> [!TIP]
>
> Si su objetivo es obtener tantas actualizaciones de pronóstico como sea posible durante el día, usar valores reales estimados y atenuación automática no es la mejor opción. Reducirá la cantidad de actualizaciones de pronóstico posibles.

##### Entrada clave: Generación fotovoltaica real para su sitio

La generación se obtiene a partir de los datos históricos de una o varias entidades de sensor. Una instalación de un solo inversor solar fotovoltaico probablemente tendrá un único sensor de "aumento total" que proporciona un valor de "generación fotovoltaica" o "exportación fotovoltaica" ( *no* exporta a la red, sino que exporta desde el tejado a partir del sol). Cada inversor tendrá un valor, y se pueden suministrar todas las entidades de sensor, que luego se totalizarán para todos los tejados.

Se debe suministrar uno o más sensores de energía creciente. Este sensor puede reiniciarse a medianoche o ser de "aumento total"; es importante que aumente a lo largo del día.

La integración determina las unidades inspeccionando el atributo `unit_of_measurement` y realiza los ajustes correspondientes. Si este atributo no está configurado, se asume que los valores son kWh. El historial de generación se actualiza a medianoche, hora local.

> [!TIP]
>
> Para que la integración pueda detectar la generación fotovoltaica anómala, es necesario que las entidades de generación informen periódicamente a Home Assistant. Se admiten las entidades que informan periódicamente el último valor de generación o que aumentan en intervalos regulares. Si su entidad de generación fotovoltaica no sigue un patrón de generación similar, es posible que la atenuación automática no sea adecuada.

> [!NOTE]
>
> No incluya entidades de generación para sitios de azoteas "remotas" que se hayan excluido explícitamente de los totales del sensor. La atenuación automática no funciona en las azoteas excluidas.

##### Entrada opcional: Exportación del sitio a la red, combinada con un valor límite

Cuando el excedente de energía generada localmente se exporta a la red eléctrica, es probable que exista un límite en la cantidad de energía exportable. La integración puede monitorizar esta exportación y, cuando se detectan periodos de "limitación de exportación" (porque la exportación se mantiene en el valor límite durante cinco minutos o más), el periodo de generación se excluye de cualquier consideración de amortiguación automática para *todos* los días considerados por esta de forma predeterminada. Este mecanismo permite diferenciar entre la generación limitada por la sombra de un árbol o una chimenea, o la limitación de la exportación en un sitio artificial.

La exportación a la red generalmente ocurre al mediodía, un momento en el que rara vez se ve afectado por el sombreado.

Se permite un solo sensor de energía creciente, que puede reiniciarse a cero a medianoche. El límite de exportación opcional solo se puede especificar en kW. Consulte la sección de opciones avanzadas para ver cómo modificar esta exclusión de "todos los días".

> [!TIP]
>
> Es posible que algunos componentes del sistema fotovoltaico no midan con precisión el valor límite de exportación como el límite real. Esto puede generar confusión, pero la razón se debe a las variaciones en los circuitos de medición de las pinzas de TC.
>
> Ejemplo: Con un límite de exportación de 5,0 kW, una puerta de enlace Enphase puede medir exactamente 5,0 kW, pero una puerta de enlace de batería Tesla en la misma instalación puede medir la misma potencia, 5,3 kW. Si el valor del sensor utilizado para la amortiguación automática proviene de la puerta de enlace Tesla en este caso, asegúrese de que el límite de exportación especificado sea 5,3.

##### Activación inicial

Para que la amortiguación automática funcione, debe tener acceso a un conjunto mínimo de datos. El historial de generación se carga inmediatamente desde el historial del sensor (o sensores), pero el historial real estimado de Solcast se recibirá después de la medianoche (hora local). Por ello, al activarse la función, es casi seguro que no modelará inmediatamente ningún factor de amortiguación.

(Si se trata de una nueva instalación en la que los valores reales estimados se obtienen una sola vez, los factores se pueden modelar inmediatamente).

> [!TIP]
>
> La mayoría de los mensajes de amortiguación automatizada se registran en el nivel `DEBUG` . Sin embargo, los mensajes que indican que los factores de amortiguación aún no se pueden modelar (y el motivo) se registran en el nivel `INFO` . Si el nivel mínimo de registro para la integración es `WARNING` o superior, no verá estas notificaciones.

##### Modificación del comportamiento de amortiguación automatizada

La amortiguación automatizada es adecuada para muchas personas, pero hay situaciones en las que no es adecuada una vez implementada. En estas situaciones, los usuarios avanzados podrían necesitar modificar el comportamiento.

La base de la amortiguación automatizada es que el valor de la generación fotovoltaica debe ser una medición fiable en comparación con la generación real estimada. Si este valor no es fiable debido a una restricción artificial (limitación), la amortiguación automatizada debe detectarlo. Para la limitación simple de la exportación de servicios públicos a un valor fijo, esto es sencillo y está integrado, pero también es posible indicar que la generación fotovoltaica en un intervalo determinado no es fiable debido a circunstancias más complejas.

Aquí es donde puede ser creativo con un sensor con plantilla específicamente nombrado para hacer que se ignoren los intervalos de generación de PV cuando no se puede confiar en que sean precisos (es decir, no en producción "completa").

Algunos ejemplos incluyen la imposibilidad de exportar a la red o la decisión de no hacerlo. En estos casos, el consumo de los hogares se equiparará a la generación, lo que confundirá la amortiguación automática.

Para modificar el comportamiento de la amortiguación automática, se puede crear una entidad de plantilla llamada `solcast_suppress_auto_dampening` . Esto puede hacerse usando la plataforma "sensor", "binary_sensor" o "switch".

La integración supervisará esta entidad para detectar cambios de estado. Cuando un estado es "activado", "1", "verdadero" o "Verdadero" en *cualquier momento de un intervalo de generación fotovoltaica de media hora* , esto indicará a la atenuación automática que modifique su comportamiento y excluya ese intervalo. Si el estado de la entidad es "desactivado", "0", "falso" o "Falso" durante *todo el intervalo* , este se incluirá de forma normal en la atenuación automática.

La supresión también es complementaria a la proporcionada por la detección del límite de exportación del sitio, por lo que esos aspectos de configuración probablemente deberían eliminarse o considerarse cuidadosamente.

También debe tener historial de cambios de estado para que tenga sentido, por lo que comenzar llevará tiempo. Esta capacidad requiere sentido común y paciencia.

> [!TIP]
>
> También configure la opción avanzada `automated_dampening_no_limiting_consistency` como `true` si es necesario.
>
> El comportamiento predeterminado es que si se detecta una limitación para cualquier intervalo en cualquier día, ese intervalo se ignorará durante todos los días de los últimos catorce días, a menos que esta opción esté habilitada.

A continuación se muestra una posible secuencia de implementación:

1. Cree la entidad `solcast_suppress_auto_dampening` con plantilla.
2. Desactive la amortiguación automática porque estará rota y será confusa (pero ya estaba rota y era confusa antes porque no puede exportar o elige no hacerlo debido al precio mayorista negativo).
3. Elimina el archivo `/config/solcast_solar/solcast-generation.json` . Es probable que el historial altere los resultados de la amortiguación automática.
4. Asegúrese de que el registrador esté configurado con un valor de al menos siete días `purge_keep_days` . Al habilitar la atenuación automática, intentará cargar hasta siete días del historial de generación (existe una opción avanzada para obtener más). Déjelo para cuando llegue el momento. Si suele purgar de forma más agresiva, puede volver a configurarlo en una semana. (No es necesario deshabilitar la adquisición de datos reales estimados).
5. Establezca la opción avanzada `automated_dampening_no_limiting_consistency` en `true` si es necesario
6. Reinicie completamente HA para habilitar la configuración del grabador y lograr que la integración de Solcast comprenda que ahora faltan datos de generación.
7. Espere pacientemente una semana para construir el historial de la nueva entidad.
8. Active la amortiguación automática y observe cómo funciona con su entidad de adaptación.

Tener habilitado el registro de nivel `DEBUG` para la integración revelará lo que sucede, lo cual es recomendable durante la configuración. Si necesita ayuda, es *fundamental* tener los registros a mano y compartirlos.

##### Notas de amortiguación automatizadas

Un factor modelado superior a 0,95 se considera insignificante y se ignora. Se agradecen comentarios sobre si estos pequeños factores deberían ser significativos y utilizarse.

Estos pequeños factores se corregirían según la generación prevista, por lo que no se justificaría ignorarlos. Sin embargo, una desviación pequeña y regular del pronóstico probablemente se deba a una configuración incorrecta del tejado o a una desviación estacional, y no al sombreado.

El objetivo de la atenuación automática no es corregir errores de configuración en la azotea de Solcast, ni las peculiaridades de generación del tipo de panel, ni mejorar la previsión. El objetivo es detectar una generación real consistentemente inferior a la prevista debido a factores locales.

> [!TIP]
>
> Si tiene dos semanas de datos históricos acumulados y se generan factores de atenuación cada media hora cuando sale el sol, es casi seguro que tiene un problema de configuración. La generación nunca coincide con la generación real estimada, y es probable que la configuración de su sitio de azotea Solcast sea incorrecta.

Cualquier configuración incorrecta en la azotea puede tener un impacto significativo en el pronóstico reportado, pero esto debe corregirse en la configuración de la azotea. Es muy recomendable comprobar que la configuración es correcta y que los pronósticos son razonablemente precisos en días de buena generación antes de intentar configurar la atenuación automática. Dicho de otro modo, si se observa un pronóstico cuestionable, desactive la atenuación automática antes de diagnosticarlo.

Los ajustes realizados mediante la amortiguación automática pueden obstaculizar los esfuerzos para resolver problemas básicos de configuración incorrecta y, si está habilitada, informar un problema de desviación del pronóstico en el que no está implicada probablemente impedirá la resolución del problema.

Todos no queremos eso.

Los sensores de energía externos (como los de exportación fotovoltaica y exportación de sitio) deben tener una unidad de medida de mWh, Wh, kWh o MWh, y deben aumentar acumulativamente a lo largo de un día determinado. Si no se puede determinar una unidad de medida, se asume que es kWh. Otras unidades como GWh o TWh no tienen sentido en un entorno residencial, y su uso resultaría en una pérdida inaceptable de precisión al convertirlas a kWh, por lo que no son compatibles. Otras unidades de energía como julios y calorías tampoco son compatibles, ya que son unidades poco comunes para la electricidad.

##### Comentario

Sus comentarios sobre su experiencia con la función de amortiguación automatizada serán bienvenidos en las discusiones del repositorio de integración.

El registro completo a nivel `DEBUG` ocurre cuando se habilita la amortiguación automática, y se le recomienda examinar e incluir ese detalle registrado en cualquier discusión que pueda señalar una deficiencia, una experiencia (¡tanto positiva como negativa!) o una oportunidad de mejora.

#### Amortiguación horaria simple

Puede cambiar el valor del factor de atenuación para cualquier hora. Los valores válidos son de 0,0 a 1,0. Un valor de 0,95 atenuará (reducirá) cada valor de los datos de pronóstico de Solcast en un 5 %. Esto se refleja en los valores y atributos del sensor, así como en el panel de control de energía de Home Assistant.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png" width="500">

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png" width="500">

> [!TIP]
>
> La mayoría de los usuarios de la configuración de amortiguación no introducen valores directamente en la configuración. En su lugar, crean automatizaciones para establecer valores adecuados a su ubicación en diferentes días o estaciones, y estas ejecutan la acción `solcast_solar.set_dampening` .
>
> Los factores que pueden hacer que la amortiguación sea apropiada pueden ser cuando se producen diferentes grados de sombreado al comienzo o al final del día en diferentes estaciones, o cuando el sol está cerca del horizonte y puede provocar que los edificios o árboles cercanos proyecten una sombra larga.

#### Amortiguación granular

Es posible configurar la atenuación para sitios Solcast individuales o usar intervalos de media hora. Esto requiere usar la acción `solcast_solar.set_dampening` o crear o modificar un archivo llamado `solcast-dampening.json` en la carpeta de configuración de Home Assistant.

La acción acepta una cadena de factores de amortiguación y un ID de recurso de sitio opcional. (El sitio opcional puede especificarse mediante guiones o guiones bajos). Para la amortiguación horaria, proporcione 24 valores. Para la amortiguación cada media hora, 48. Al llamar a la acción, se crea o actualiza el archivo `solcast-dampening.json` cuando se especifica un sitio o 48 valores de factor. Si se configura la amortiguación general con 48 factores, se puede especificar un sitio opcional para "todos" (o simplemente omitirlo para este caso de uso).

```yaml
action: solcast_solar.set_dampening
data:
  damp_factor: 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
  #site: 1234-5678-9012-3456
```

Si no se especifica un ID de recurso de sitio y se proporcionan 24 valores de atenuación, se eliminará la atenuación granular y la atenuación horaria general configurada se aplicará a todos los sitios. (La atenuación granular también se puede desactivar mediante el cuadro de diálogo `CONFIGURE` integración).

No es necesario ejecutar la acción. En su lugar, el archivo puede actualizarse directamente y, si se crea o modifica, se leerá y utilizará. Las operaciones de creación, actualización y eliminación de este archivo se supervisan, y los cambios resultantes en el pronóstico atenuado se reflejarán en menos de un segundo después de la operación.

Si se configura la amortiguación granular para un solo sitio en una configuración multisitio, dicha amortiguación solo se aplicará a los pronósticos de ese sitio. Los demás sitios no se amortiguarán.

Por supuesto, se puede configurar la amortiguación para todos los sitios individuales y, cuando este sea el caso, todos los sitios deben especificar la misma cantidad de valores de amortiguación, ya sea 24 o 48.

<details><summary><i>Haga clic para ver ejemplos de archivos de amortiguación</i></summary>
</details>

Los siguientes ejemplos pueden usarse como punto de partida para el formato de amortiguación granular basada en archivos. Asegúrese de usar los ID de recursos de su sitio web en lugar de los ejemplos. El archivo debe guardarse en la carpeta de configuración de Home Assistant y llamarse `solcast-dampening.json` .

Ejemplo de amortiguación horaria para dos sitios:

```yaml
{
  "1111-aaaa-bbbb-2222": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "cccc-4444-5555-dddd": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Ejemplo de amortiguación horaria para un solo sitio:

```yaml
{
  "eeee-6666-7777-ffff": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Ejemplo de amortiguación cada media hora para dos sitios:

```yaml
{
  "8888-gggg-hhhh-9999": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "0000-iiii-jjjj-1111": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Ejemplo de amortiguación cada media hora para todos los sitios:

```yaml
{
  "all": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```




#### Lectura de valores de pronóstico en una automatización

La acción `solcast_solar.query_forecast_data` puede devolver pronósticos atenuados y no atenuados (incluya `undampened: true` ). El sitio también puede incluirse en los parámetros de la acción si se desea un desglose. (El sitio opcional puede especificarse mediante guiones o guiones bajos).

```yaml
action: solcast_solar.query_forecast_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
  undampened: true
  #site: 1111-aaaa-bbbb-2222
```

El historial de pronóstico sin amortiguar se conserva solo durante 14 días.

#### Lectura de valores reales estimados en una automatización

Al calcular la amortiguación mediante una automatización, puede ser beneficioso utilizar valores pasados reales estimados como entrada.

Esto es posible mediante la acción `solcast_solar.query_estimate_data` . Es posible que el sitio no esté incluido actualmente en los parámetros de la acción. (Si desea obtener un desglose del sitio, plantee un problema o un tema de discusión).

```yaml
action: solcast_solar.query_estimate_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
```

Los datos reales estimados se conservan durante 730 días.

#### Lectura de valores de amortiguación

Los factores de amortiguamiento configurados actualmente se pueden recuperar mediante la acción "Pronóstico fotovoltaico de Solcast: Obtener amortiguamiento de pronósticos" ( `solcast_solar.get_dampening` ). Esta acción puede especificar un ID de recurso de sitio opcional, o bien, especificar ningún sitio o especificar "todos". Si no se especifica ningún sitio, se devolverán todos los sitios con amortiguamiento configurado. Se generará un error si un sitio no tiene amortiguamiento configurado.

El sitio opcional puede especificarse mediante guiones o guiones bajos. Si la llamada al servicio utiliza guiones bajos, la respuesta también los utilizará.

Si la amortiguación granular se configura para especificar tanto los factores de amortiguación de cada sitio como los de "todos" los sitios, al intentar recuperar los factores de amortiguación de un sitio individual, se devolverán los de "todos" los sitios, y se indicará el sitio "todos" en la respuesta. Esto se debe a que, en este caso, un conjunto de factores de amortiguación "todos" anula la configuración de cada sitio.

Ejemplo de llamada:

```yaml
action: solcast_solar.get_dampening
data:
  site: b68d-c05a-c2b3-2cf9
```

Ejemplo de respuesta:

```yaml
data:
  - site: b68d-c05a-c2b3-2cf9
    damp_factor: >-
      1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0
```

### Configuración de los atributos del sensor

Hay bastantes atributos de sensores que se pueden usar como fuente de datos para sensores de plantilla, gráficos, etc., incluido un desglose por sitio, valores estimados 10/50/90 y un desglose detallado por hora y media hora para cada día de pronóstico.

Muchos usuarios no utilizarán estos atributos, por lo que para reducir el desorden (especialmente en la interfaz de usuario y también en el almacenamiento de estadísticas de la base de datos), todos ellos se pueden desactivar si no son necesarios.

De forma predeterminada, todos están habilitados, excepto los atributos detallados por sitio y detallado por hora. (Los atributos de detalle por hora y media hora no se envían a la grabadora de Home Assistant, ya que son muy grandes, generarían un crecimiento excesivo de la base de datos y son de poca utilidad a largo plazo).

> [!NOTE]
>
> Si desea implementar el gráfico PV de muestra a continuación, deberá mantener habilitado el desglose de detalles cada media hora, junto con `estimate10` .

### Configuración de límite duro

Existe una opción para establecer un "límite estricto" para la salida proyectada del inversor, y este límite "recortará" los pronósticos de Solcast a un valor máximo.

El límite máximo puede establecerse como un valor general (aplicable a todos los sitios de todas las cuentas Solcast configuradas) o puede establecerse por cuenta Solcast con un valor de límite máximo independiente para cada clave API. (En este último caso, separe con comas los valores de límite máximo deseados).

El escenario que requiere el uso de este límite es sencillo, pero tenga en cuenta que casi ninguna instalación fotovoltaica lo necesitará. (Y si tiene microinversores o un inversor por cadena, definitivamente no. Lo mismo aplica para todos los paneles con la misma orientación en un mismo sitio Solcast).

Considere un escenario con un solo inversor de cadena de 6 kW y dos cadenas conectadas, cada una con una generación potencial de 5,5 kW, orientadas en direcciones separadas. Esto se considera "sobredimensionado" desde la perspectiva del inversor. No es posible establecer un límite de generación de CA para Solcast que se adapte a este escenario cuando se configura con dos ubicaciones, ya que a media mañana o por la tarde en verano, una cadena puede generar 5,5 kW de CC, lo que resulta en 5 kW de CA, y la otra cadena probablemente también generará. Por lo tanto, establecer un límite de CA en Solcast para cada cadena en 3 kW (la mitad del inversor) no tiene sentido. Establecerlo en 6 kW para cada cadena tampoco tiene sentido, ya que Solcast casi con seguridad sobreestimará la generación potencial.

El límite máximo puede establecerse en la configuración de integración o mediante la acción de servicio `solcast_solar.set_hard_limit` en `Developer Tools` . Para desactivarlo, introduzca un valor de cero o 100 en el cuadro de diálogo de configuración. Para desactivarlo mediante una llamada a la acción de servicio, utilice `solcast_solar.remove_hard_limit` . (No se puede especificar cero al ejecutar la acción de configuración).

### Configuración de sitios excluidos

Es posible excluir uno o más sitios Solcast del cálculo de los totales de sensores y del pronóstico del tablero de energía.

El caso de uso consiste en permitir que uno o más sitios locales "principales" representen los valores de pronóstico combinados, y que un sitio "remoto" se visualice por separado con gráficos Apex o sensores de plantilla que obtienen su valor de los atributos de los sensores de desglose del sitio. Tenga en cuenta que no es posible crear una fuente independiente del panel de energía a partir de sensores de plantilla (estos datos provienen directamente de la integración como un diccionario de datos).

Utilizar esta función avanzada junto con sensores de plantilla y gráficos Apex no es sencillo. Sin embargo, en el archivo README se incluyen ejemplos tanto para sensores de plantilla creados a partir de datos de atributos como para un gráfico Apex. Consulte [Interacción](#interacting) , [Sensores de plantilla de ejemplo](#sample-template-sensors) y [Gráfico Apex de ejemplo para el panel](#sample-apex-chart-for-dashboard) .

La configuración se realiza a través del diálogo `CONFIGURE` .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites1.png" width="500">

Seleccionar los sitios que se excluirán y hacer clic en `SUBMIT` surtirá efecto de inmediato. No es necesario esperar la actualización del pronóstico.

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/ExcludeSites2.png" width="500">

> [!NOTE]
>
> Los nombres de los sitios y los ID de los recursos provienen de los sitios conocidos al momento de la última obtención de sitios de Solcast (al inicio). No es posible agregar una nueva clave API y seleccionar un sitio para excluirlo de la nueva cuenta. Primero debe agregarse la nueva cuenta, lo que reiniciará la integración y cargará los nuevos sitios. Después, se podrán seleccionar los sitios que se excluirán de la nueva cuenta.

### Opciones de configuración avanzadas

Es posible cambiar el comportamiento de algunas funciones de integración, especialmente para la amortiguación automatizada integrada.

Estas opciones se pueden configurar creando un archivo llamado `solcast-advanced.json` en el directorio de configuración de Home Assistant Solcast Solar (normalmente `/config/solcast_solar` ).

Para conocer las opciones disponibles, consulte la documentación en [Opciones avanzadas](https://github.com/BJReplay/ha-solcast-solar/blob/main/ADVOPTIONS.md) .

## Sensores de plantilla de muestra

### Combinando datos del sitio

Un deseo potencial es combinar los datos de pronóstico para múltiples sitios comunes a una cuenta Solcast, lo que permite la visualización de datos detallados de cuentas individuales en un gráfico de Apex.

Este código es un ejemplo de cómo hacerlo utilizando un sensor de plantilla, que suma todos los intervalos de pronóstico pv50 para brindar un total de cuenta diaria, además de crear un atributo detailedForecast de todos los datos de intervalo combinados para usar en una visualización.

Los desgloses del sitio deben estar habilitados en las opciones de integración (el desglose del pronóstico detallado no está habilitado de forma predeterminada).

**Revelar código**

<details><summary><i>haga clic aquí</i></summary>
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




## Ejemplo de gráfico de Apex para el panel de control

El siguiente YAML genera un gráfico de la generación fotovoltaica actual, el pronóstico fotovoltaico y el pronóstico fotovoltaico para 2010. Requiere la instalación de [Apex Charts](https://github.com/RomRider/apexcharts-card) .

[](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png">

Personalice con los sensores Home Assistant adecuados la generación solar total actual y la salida de energía fotovoltaica de los paneles solares.

> [!NOTE]
>
> El gráfico asume que los sensores solares fotovoltaicos están en kW, pero si algunos están en W, agregue la línea `transform: "return x / 1000;"` debajo del ID de entidad para convertir el valor del sensor a kW.

**Revelar código**

<details><summary><i>haga clic aquí</i></summary>
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




## Problemas conocidos

- Modificar el límite máximo modificará el historial de pronósticos registrado. Esto es intencional y podría no cambiar.
- Cualquier archivo JSON de integración de longitud cero se eliminará al iniciar (ver a continuación)
- Los sitios de muestra (si están configurados en su panel de Solcast) se incluirán en sus pronósticos recuperados por esta integración y se devolverán a Home Assistant (ver a continuación)

### Eliminación de archivos de longitud cero

Anteriormente, la integración ha escrito archivos de caché como archivos de longitud cero. Esto ha sido increíblemente poco frecuente y puede servir como recordatorio para realizar copias de seguridad de la instalación.

La causa puede ser un problema de código (que se ha analizado repetidamente y probablemente se haya solucionado en v4.4.8) o algún factor externo que no podemos controlar, pero definitivamente ocurre al apagar, y la integración (anteriormente) no se reinicia, generalmente después de que se ha actualizado.

Los datos desaparecieron. La solución fue eliminar el archivo vacío o restaurarlo desde una copia de seguridad y luego reiniciar.

A partir de la v4.4.10, se iniciará con el archivo vacío y se registrará un evento `CRITICAL` que indica que se ha eliminado el archivo de longitud cero. Esto provocará un uso adicional de llamadas a la API al inicio. ***Probablemente se perderá todo el historial de pronósticos.***

Se esperan problemas con el uso de la API, que se solucionarán en 24 horas.

### Sitios de muestra

Si ve sitios de muestra (como estos [](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png)<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SampleSites.png"> ) elimínelos de su panel de Solcast.

## Solución de problemas

<details><summary><i>Haga clic aquí para ampliar los consejos para la solución de problemas.</i></summary>
</details>

Esta integración tiene como objetivo registrar muy poco cuando todo funciona correctamente. Cuando se producen problemas, se generan entradas de registro `ERROR` o `CRITICAL` , y cuando ocurren problemas temporales o menores, se generan entradas `WARNING` . Siempre revise los registros como primer paso para solucionar un problema.

Para permitir un registro más detallado, muchas entradas se emiten en el nivel `DEBUG` . Se recomienda habilitar el registro de depuración para facilitar la resolución de problemas. Tenga en cuenta que cambiar el nivel de registro requerirá reiniciar Home Assistant, lo que cambiará el nombre del archivo `homeassistant.log` actual a `homeassistant.log.1` (no existe `.2` , por lo que solo se puede acceder a esta sesión y a la anterior).

En `/homeassistant/configuration.yaml` :

```
logger:
  default: warn
  logs:
    custom_components.solcast_solar: debug
```

Revisar los registros es bastante sencillo, pero los registros de depuración no se pueden consultar desde la interfaz de usuario. Es necesario consultar el archivo `/homeassistant/home-assistant.log` . Desde una sesión SSH, use `less /homeassistant/home-assistant.log` . Puede que tenga otras formas de ver este archivo según los complementos instalados.

### Problemas con la clave API

Durante la configuración, se introduce una o varias claves API, y los sitios configurados en solcast.com se recuperarán en ese momento para probar la clave. Los fallos suelen clasificarse en varias categorías: la clave es incorrecta, la cuenta de Solcast no tiene sitios configurados o no se puede acceder a solcast.com. Estas situaciones son, en la mayoría de los casos, evidentes.

Si no se puede acceder a solcast.com, generalmente debería buscar otros problemas. Si ocurre una condición transitoria, como recibir un error `429/Try again later` , siga las instrucciones: espere y vuelva a intentar la configuración inicial. (El sitio web de Solcast suele saturarse de solicitudes en intervalos de quince minutos, sobre todo al principio de cada hora).

### Problemas con la actualización del pronóstico

Cuando se actualiza el pronóstico, la integración incorpora un mecanismo de reintento para gestionar situaciones transitorias de tipo `429/Try again later` . Es muy raro que los diez intentos fallen; sin embargo, se sabe que ha ocurrido a primera hora de la mañana europea. Si ocurre, la siguiente actualización se realizará con casi total seguridad.

Se mantiene un contador de uso de la API para registrar el número de llamadas realizadas a solcast.com cada día (que comienza a medianoche UTC). Si este contador no se ajusta a la realidad, al detectar un rechazo de llamada a la API, se establecerá en su valor máximo y no se reiniciará hasta medianoche UTC.

### Los valores pronosticados parecen "simplemente incorrectos"

Es posible que aún haya sitios de demostración configurados en solcast.com. Compruébelo y, si aún están configurados, elimínelos.

También revise el azimut, la inclinación, la ubicación y otras configuraciones de los sitios. Los valores "simplemente incorrectos" no se deben a la integración, sino que indican que algo falla en la configuración general.

### Excepciones en los registros

Las excepciones nunca deben registrarse a menos que algo esté muy mal. Si se registran, suelen ser un síntoma de la causa subyacente, no un defecto del código, y generalmente no están directamente relacionadas con la causa raíz del problema. Considere posibles causas como algo que haya cambiado.

Cuando ocurren excepciones, es probable que los estados del sensor pasen a `Unavailable` , lo que también es un síntoma de que se ha producido una excepción.

Si está actualizando una integración de Solcast muy antigua o completamente diferente, no se trata de una actualización. Es una migración, así que considérelo como tal. Se incluyen algunos escenarios de migración, pero otros pueden requerir la eliminación completa de todos los datos incompatibles que puedan estar causando problemas graves. Consulte ["Eliminación completa de la integración"](#complete-integration-removal) para comprender la ubicación de algunos archivos que podrían estar interfiriendo.

Dicho esto, los defectos de código pueden ocurrir, pero no deberían ser la primera sospecha. Antes de un lanzamiento, se realizan exhaustivas pruebas automatizadas de este código con PyTest. Estas pruebas abarcan una amplia gama de escenarios y ejecutan cada línea de código. Algunas de estas pruebas anticipan lo peor en situaciones que pueden causar excepciones, como la corrupción de datos en caché, y en estas situaciones se esperan excepciones.

### Palabra final

Si se encuentra un comportamiento muy extraño, lleno de excepciones, una solución rápida puede ser hacer una copia de seguridad de todos los archivos `/homeassistant/solcast*.json` , eliminarlos y luego reiniciar la integración.




## Eliminación completa de la integración

Para eliminar por completo todos los rastros de la integración, comience navegando a `Settings` | `Devices & Services` | `Solcast PV Forecast` , haga clic en los tres puntos junto al ícono de engranaje ( `CONFIGURE` en las primeras versiones de HA) y seleccione `Delete` .

En este punto, los ajustes de configuración se han restablecido, pero los cachés de información de código y pronóstico seguirán existiendo (al configurar nuevamente la integración se reutilizarán estos datos almacenados en caché, lo que puede ser deseable o no).

Las cachés residen en la carpeta de configuración de Home Assistant Solcast Solar (normalmente `/config/solcast_solar` o `/homeassistant/solcast_solar` , pero su ubicación puede variar según el tipo de implementación de Home Assistant). Estos archivos reciben el nombre de la integración y se pueden eliminar con `rm solcast*.json` .

El código en sí reside en `/config/custom_components/solcast_solar` y al eliminar esta carpeta completa se completará la eliminación total de la integración.

## Cambios

versión 4.4.11

- Corregir la validación de opciones avanzadas para `not_set_if` por @autoSteve
- Agregar traducción faltante, ES, FR, PL, SK, UR por @GitLocalize
- Espaciado consistente de archivos de cadenas por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.10...v4.4.11

versión 4.4.10

- Corregir la excepción de problemas reparables que faltan registros por @autoSteve
- Se solucionó el problema cuando faltaba el historial de pronóstico (#423) por @autoSteve
- Eliminar archivos de caché de longitud cero al inicio por @autoSteve
- Agregar opción avanzada granular_dampening_delta_adjustment de @autoSteve
- Cambiar el nombre de automatic_dampening_no_delta_adjustment por @autoSteve
- Advertencia de desuso y problema con las opciones avanzadas por @autoSteve
- Agregar problema planteado para situaciones de error de opciones avanzadas por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.9...v4.4.10

versión 4.4.9

- Agregar variantes de modelo con opción avanzada de amortiguación automática por @Nilogax
- Agregar opción avanzada de ajuste delta de amortiguación automática por @Nilogax
- Agregar opción avanzada de amortiguación automática para preservar los factores anteriores por @Nilogax
- Agregar opción avanzada de supresión de amortiguación automática de entidades por @autoSteve
- Agregar soporte de plataforma de conmutación para entidad de supresión de generación por @autoSteve
- La entidad de supresión ahora puede comenzar y finalizar el día cada día en cualquier estado por @autoSteve
- Refinar el comportamiento de inicio y traducir los mensajes de estado de inicio por @autoSteve
- Corregir la actualización de la entidad de amortiguación en la amortiguación horaria establecida por acción para todos los 1.0 por @autoSteve
- Se solucionó un error benigno relacionado con el inicio cuando los datos reales estimados aún no fueron adquiridos por @autoSteve
- Se corrige la excepción cuando se usa la amortiguación por hora y la entidad de amortiguación está habilitada por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.8...v4.4.9

versión 4.4.8

- Mueva todos los archivos de caché y configuración a `config/solcast_solar` por @autoSteve
- Agregar API Solcast temporalmente no disponible problema planteado por @autoSteve
- Se mejora el aviso de reparación "Falta información sobre pronósticos futuros cuando la actualización automática está habilitada" de @gcoan
- No sugiera un aviso de reparación "reparable" para la actualización manual después de fallas de la API por @autoSteve
- Ignorar los factores de amortiguación automáticos ajustados por encima del umbral "insignificante" de @autoSteve
- Agregar opción avanzada de amortiguación automática 'factor insignificante ajustado' por @autoSteve
- Agregar opción avanzada de amortiguación automática 'pico similar' por @autoSteve
- Agregar opción avanzada de amortiguación automática 'retardo de obtención de generación' por @autoSteve
- Agregar opción avanzada de estimaciones reales 'desglose del mapa de registro' por @autoSteve
- Agregar opción avanzada de estimaciones reales 'log ape percentiles' por @autoSteve
- Agregar opción avanzada de estimaciones reales 'fetch delay' de @autoSteve
- Agregar opción general avanzada 'agente de usuario' por @autoSteve
- Modificar la opción avanzada de amortiguación automática 'intervalos mínimos de coincidencia' para aceptar `1` por @autoSteve
- Consistencia de atributos como zona horaria local para valores de fecha y hora por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.7...v4.4.8

versión 4.4.7

- Agregar archivo de configuración de opciones avanzadas por @autoSteve
- Agregar el atributo `custom_hours` al sensor `Forecast Next X Hours` por @autoSteve
- Amortiguación automática, mejora de la exclusión de generación no confiable en intervalos por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.6...v4.4.7

versión 4.4.6

- Corrección: Amortiguación automática, ignorar los días de generación con una pequeña cantidad de muestras de historial por @autoSteve
- Corrección: restringir el modelado de amortiguación automática a 14 días (dependía del historial de generación) por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.5...v4.4.6

versión 4.4.5

- Transición entre Europa y Dublín entre horario estándar e invierno adaptada por @autoSteve
- Amortiguación automática, utilización de detección de anomalías intercuartiles para entidades de generación por @autoSteve
- Amortiguación automática, adaptación a entidades de generación consistentes en la generación o en el tiempo por @autoSteve
- Amortiguación automática: ignora intervalos de generación completos que tienen anomalías por @autoSteve
- Amortiguación automática, el número mínimo de intervalos coincidentes debe ser mayor que uno por @autoSteve
- Amortiguación automática, agrega soporte para entidades de supresión de generación por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.4...v4.4.5

versión 4.4.4

- Corrección: Amortiguación automática, intervalo ajustado del horario de verano por @rcode6 y @autoSteve
- Eliminar y suprimir problemas de azimut inusuales ignorados por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.3...v4.4.4

versión 4.4.3

- Obtención aleatoria de datos reales y luego modelado de amortiguación automática inmediato por @autoSteve
- Excluir entidades con amortiguación automática deshabilitada de la selección por @autoSteve
- Amortiguación automática, excluir intervalos limitados por exportación de todos los días por @autoSteve
- Amortiguación automática, transiciones de horario de verano gestionadas por @autoSteve
- Obtenga hasta catorce días de datos de pronóstico de @autoSteve
- Corrección: Actualización del gráfico de factores de amortiguación de TEMPLATES.md por @jaymunro
- Corrección: Actualización del error tipográfico en el nombre del sensor en TEMPLATES.md por @gcoan
- Versión mínima de HA 2025.3

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.2...v4.4.3

versión 4.4.2

- Amortiguación automática, adaptación a la actualización periódica de entidades de generación (Envoy) por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.1...v4.4.2

versión 4.4.1

- Generación/exportación de unidad de medida de ajuste automático por @brilthor y @autoSteve
- Ignorar saltos atípicos de entidades generacionales por @autoSteve
- Se requiere un acuerdo de generación de la mayoría de los datos reales de "buenos días" para la amortiguación automática por @autoSteve
- @Nilogax agregó un ejemplo de gráfico de amortiguación automática de aplicado vs. base a TEMPLATES.md. ¡Gracias!
- Amplias actualizaciones del archivo README.md sobre amortiguación automática por parte de @autoSteve, @gcoan y @Nilogax. ¡Gracias!
- Solución: Migración de uso sin reinicio, cambio de clave sin cambio de sitios por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.4.0...v4.4.1

versión 4.4.0

- Añade la función de amortiguación automática por @autoSteve
- Los factores de amortiguación modificados se aplican desde el comienzo del día actual por @autoSteve
- Corrección del tamaño máximo de atributo de los sensores traducidos excedido por @autoSteve
- Supervisar solcast-dampening.json para crear/actualizar/eliminar por @autoSteve
- Agregar el atributo last_attempt a la entidad api_last_polled por @autoSteve
- Agregar parámetro de sitio de acción permitida con guion o guión bajo por @autoSteve
- Agregar prueba para azimut inusual por @autoSteve
- Corregir los puntos de inicio y fin del panel de energía por @autoSteve
- Atributos de atribución solo donde corresponde el crédito por @autoSteve
- Versión mínima de HA 2024.11

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.5...v4.4.0

### Cambios previos

<details><summary><i>Haga clic aquí para volver a la versión v3.0</i></summary>
</details>

versión 4.3.5

- Se corrige la detección de cambio de clave API en 429 al usar múltiples claves por @autoSteve
- Se solucionó el caso especial de validación de clave que podría impedir el inicio por parte de @autoSteve
- Agregar atributos de recuento de fallas de actualización al último sensor sondeado por @autoSteve
- Permitir la obtención de sitios cuando falla cada 30 minutos en la tormenta 429 de @autoSteve
- Comprobación de tipos más estricta por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.4...v4.3.5

versión 4.3.4

- Incluir etiquetas de sitios en la azotea en los atributos del sensor del sitio por @autoSteve
- Eliminar la molesta depuración de inicio registrada en nivel crítico por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.3...v4.3.4

versión 4.3.3

- Agregar sitios para excluir de los totales y del panel de energía por @autoSteve
- Añadir traducción al portugués por @ViPeR5000 (¡gracias!)
- Limpiar los sensores de diagnóstico de límite duro huérfanos por @autoSteve
- Evitar el bloqueo de inicio. Reinicio de HA llamando repetidamente a rooftop_sites por @autoSteve
- Corrección de los valores del sensor de diagnóstico para el límite estricto de claves multi-API por @autoSteve
- Se solucionó la eliminación de caché huérfana donde la clave API contiene caracteres no alfanuméricos por @autoSteve
- Se corrigió que el formato de amortiguación granular de solcast-dampening.json estuviera semi-sangrado por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.2...v4.3.3

versión 4.3.2

- Reemplace el guion con un guion bajo para los nombres de atributos de desglose del sitio por @autoSteve
- Añadir traducción al español por @autoSteve
- Añadir traducción al italiano por @Ndrinta (¡gracias!)

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.1...v4.3.2

versión 4.3.1

- Agregue instrucciones de instalación predeterminadas de HACS por @BJReplay

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.3.0...v4.3.1

versión 4.3.0

- Se solucionó un problema cuando el desglose cada media hora estaba deshabilitado, pero el desglose por hora estaba habilitado por @autoSteve
- Se solucionó un problema con la transición de amortiguación granular a amortiguación heredada por @autoSteve
- Se solucionó un problema con el uso de múltiples límites estrictos por @autoSteve
- Se solucionó un problema con el inicio obsoleto cuando la actualización automática está habilitada por @autoSteve
- Agregar atributos de actualización automática a api_last_polled por @autoSteve
- Actualizar los archivos de datos del esquema de integración v3 por @autoSteve
- Los flujos de configuración y opciones verifican la clave API válida y los sitios disponibles por @autoSteve
- Agregar reautorización y reconfigurar flujos por @autoSteve
- Agregar flujos de reparación para pronósticos que no se actualizan por @autoSteve
- Obtenga datos reales estimados en un inicio súper obsoleto por @autoSteve
- Establecer sensores como no disponibles en caso de falla de integración por @autoSteve
- Detectar la clave API duplicada especificada por @autoSteve
- Eliminar la verificación de integración conflictiva de @autoSteve
- Agregar pruebas de integración y unitarias por @autoSteve
- Comprobación estricta de tipos por @autoSteve
- Agregar sección de solución de problemas en README.md por @autoSteve
- Se solucionó un problema de pronósticos incorrectos con notas para eliminar cualquier sitio de muestra del panel de Solcast por @BJReplay
- Plantilla de problema actualizada por @BJReplay

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.7...v4.3.0

versión 4.2.7

- Solucionar un problema con la validación de la clave API por @autoSteve
- Se solucionó un problema que impedía la eliminación limpia de la integración por @autoSteve
- Mejora la comprobación de integraciones conflictivas por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.6...v4.2.7

versión 4.2.6

- Se solucionó un problema que impedía nuevas instalaciones por @autoSteve
- Se solucionó un problema al calcular el intervalo de actualización automática para claves de API múltiples por @autoSteve
- Se solucionó un problema al migrar desde/hacia múltiples API para la configuración de Docker por @autoSteve
- Se solucionó un problema al borrar todo el historial de pronósticos por @autoSteve
- Se solucionó un problema en el que el recuento de API no se incrementó en la búsqueda de inicio obsoleto por @autoSteve
- Se solucionó un problema en el que @autoSteve no actualizaba la API utilizada/total ni los últimos sensores actualizados.
- Agregue el simulador de API de Solcast para respaldar el desarrollo y acelerar las pruebas por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.5...v4.2.6

versión 4.2.5

- Agregar límite estricto de claves multi-API por @autoSteve
- Limitar proporcionalmente las averías del sitio por @autoSteve
- Calcular correctamente el recuento diario del sitio según el límite estricto por @autoSteve
- Aplicación inmediata de amortiguación a pronósticos futuros por @autoSteve
- Solucionar problemas de transición al horario de verano por @autoSteve
- Corregir la excepción de salida de salud del sistema por @autoSteve
- Mejoras en el registro para el conocimiento de la situación de la información por @autoSteve
- La actualización automática tolera el reinicio justo antes de la búsqueda programada por @autoSteve
- Actualización de la traducción al polaco, gracias a @erepeo

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.4...v4.2.5

versión 4.2.4

- Agregar encabezado de agente de usuario a las llamadas API por @autoSteve
- Hacer referencia a la acción en lugar de a la llamada de servicio por @gcoan

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.3...v4.2.4

versión 4.2.3

- Se solucionó un problema que provocaba que fallara el cambio de cuentas de Solcast por @autoSteve
- Se solucionó un problema con una clave API múltiple donde @autoSteve no manejaba correctamente el restablecimiento del uso de la API
- Se solucionó un problema con el desglose detallado del sitio habilitado para los atributos por hora por @autoSteve
- Limpieza de código y algo de refactorización por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.0...v4.2.3

versión 4.2.1 / versión 4.2.2

- Lanzamientos retirados debido a problemas

versión 4.2.0

- Versión general disponible de las funciones de prelanzamiento v4.1.8 y v4.1.9
- Traducciones de respuestas de error de llamada de servicio de @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.2.0

Cambios más recientes: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.9...v4.2.0

versión preliminar de la versión 4.1.9

- Amortiguación granular para amortiguar cada media hora por @autoSteve y @isorin
- Amortiguación aplicada al obtener el pronóstico y no al historial de pronósticos por @autoSteve y @isorin
- Recupere valores de pronóstico no amortiguados mediante la llamada de servicio de @autoSteve (gracias @Nilogax)
- Obtenga los factores de amortiguación configurados actualmente mediante la llamada de servicio de @autoSteve (gracias @Nilogax)
- Migración de pronóstico no amortiguado a caché no amortiguado al inicio por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.8...v4.1.9

versión preliminar de la versión 4.1.8

- Actualizaciones de pronósticos automatizadas que no requieren automatización por @autoSteve y @BJReplay
- Agregue amortiguación por sitio por @autoSteve
- Agregue la opción de desglose del sitio para obtener pronósticos detallados por @autoSteve
- Agregar configuración de límite estricto a las opciones por @autoSteve
- Suprimir la recarga de integración cuando @autoSteve cambia muchas opciones de configuración

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.1.8

versión 4.1.7

- Se solucionan problemas con la falla del sitio para los sitios agregados posteriormente por @autoSteve
- Solucionar problemas con la avería del sitio para sensores ranurados por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.6...v4.1.7

versión 4.1.6

- Simplifique el diálogo de configuración por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.5...v4.1.6

versión preliminar de la versión 4.1.5

- Error: La marca de tiempo almacenada en el caché de uso era incorrecta por @autoSteve
- Error: Se agregó el uso de restablecimiento de clave API para la primera clave por @autoSteve
- Error: Falta un iterador en la verificación de nuevos sitios por @autoSteve
- Solución a un posible error de programación de HA por @autoSteve
- Alineación del estilo de código con las pautas de estilo HA por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.4...v4.1.5

versión preliminar de la versión 4.1.4

- Actualización de la traducción al polaco por @home409ca
- Cambiar el nombre de la integración en HACS a Solcast PV Forecast por @BJReplay
- Reducir el requisito de versión de aiofiles a &gt;=23.2.0 por @autoSteve
- Mejoras en el cuadro de diálogo de configuración por @autoSteve
- Varias actualizaciones de traducción por @autoSteve
- Refactorización del momento y construcción del spline restante por @autoSteve
- Cómo evitar un pronóstico negativo para el sensor de horas X por @autoSteve
- Suprimir el rebote del spline para reducir el spline por @autoSteve
- Serialización más cuidadosa de solcast.json por @autoSteve
- Monitorear la última marca de tiempo actualizada para sites-usage.json por @autoSteve
- Limpieza exhaustiva de código por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.3...v4.1.4

versión 4.1.3

- Acomodar la eliminación de la llamada API GetUserUsageAllowance de @autoSteve
- Reducir a la mitad los retrasos en los reintentos por @autoSteve
- Mejoras del archivo Léame por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.2...v4.1.3

versión 4.1.2

- Turno de quince minutos, porque los promedios son de 30 minutos por @autoSteve
- Aumentar los intentos de obtención de pronósticos a diez por @autoSteve
- Mover imágenes a capturas de pantalla por @BJReplay
- Se soluciona el problema de que las imágenes readme no se muestran en la interfaz de HACS

Reemplaza la versión v4.1.1

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.0...v4.1.2

versión 4.1

- Primer lanzamiento importante desde la versión v4.0.31 que no fue etiquetado como prelanzamiento
- Esos otros lanzamientos han sido en su mayoría bastante estables, pero estamos seguros de que este lanzamiento está listo para todos.
- Cambios desde la versión v4.0.31:
    - Estabilidad enormemente mejorada para todos y experiencia de inicio inicial para nuevos usuarios.
    - Atributos adicionales del sensor
    - Nuevas opciones de configuración para suprimir los atributos del sensor
    - Redacción de información confidencial en los registros de depuración
    - Eficiencia mejorada, con muchos sensores calculados en intervalos de cinco minutos, algunos solo cuando se obtienen los pronósticos
    - Interpolación de splines para sensores 'momentáneos' y 'periódicos'
    - Correcciones para usuarios de claves multi-API
    - Correcciones para usuarios de Docker
    - Mejoras en el manejo de excepciones
    - Mejoras en el registro
- @autoSteve es bienvenido como CodeOwner
- Ahora es evidente que es poco probable que este repositorio se agregue como repositorio predeterminado en HACS hasta que salga HACS 2.0, por lo que las instrucciones de instalación dejan en claro que agregar a través del flujo de Repositorio manual es el enfoque preferido y se han agregado nuevas instrucciones para mostrar cómo hacerlo.

Registro de cambios de la versión: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.1.0

Cambios más recientes: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.43...v4.1.0

versión 4.0.43

- Recuperación automática al inicio cuando @autoSteve detecta datos de pronóstico obsoletos

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.42...v4.0.43

versión 4.0.42

- Informe de fallos de carga de sitios iniciales y reintentos automáticos de HA por @autoSteve
- Suprimir el rebote de splines en splines de momento por @autoSteve
- Recalcular splines a medianoche antes de la actualización de los sensores por @autoSteve
- Actualizaciones del archivo Léame por @autoSteve
- Se eliminaron la amortiguación y el límite estricto de los desgloses de pronósticos por sitio (demasiado estrictos, demasiado engañosos) por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.41...v4.0.42

versión 4.0.41

- Pronóstico interpolado 0/30/60 corrección n.° 101 de @autoSteve
- Asegúrese de que el directorio de configuración siempre sea relativo a la ubicación de instalación #98 por @autoSteve
- Agregue state_class a `power_now_30m` y `power_now_1hr` para que coincida con `power_now` de @autoSteve (eliminará LTS, pero LTS no es útil para estos sensores)
- Utilice splines diarios de valores de pronóstico momentáneos y decrecientes de @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.40...v4.0.41

versión 4.0.40

- Pronóstico interpolado 0/30/60 de potencia y energía X horas por @autoSteve
- Asegúrese de que el directorio de configuración siempre sea relativo a la ubicación de instalación por @autoSteve
- Mejoras en el gráfico PV de muestra por @gcoan

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.39...v4.0.40

versión 4.0.39

- Actualizaciones de las descripciones de los sensores y modificación de algunos nombres de sensores por parte de @isorin (lo que podría afectar la interfaz de usuario, las automatizaciones, etc. si estos sensores estuvieran en uso. Energía en 30/60 minutos y sensor personalizado de X horas).
- Eliminar la dependencia de la biblioteca scipy por @autoSteve
- Agregar opciones de configuración granulares para los atributos por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.38...v4.0.39

versión 4.0.38

- Agregue los conceptos clave de Solcast y un gráfico de generación de PV de muestra al archivo README de @gcoan
- Agregar spline PCHIP al pronóstico restante por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.37...v4.0.38

versión 4.0.37

- Modificar el nombre del atributo para eliminar "pv_" por @autoSteve (nota: falla si ya se han usado nuevos atributos en plantillas/automatizaciones)
- Redondeo de atributos del sensor n.° 51 de @autoSteve
- Mejora el manejo de excepciones para la obtención de pronósticos por @autoSteve
- Mejorar aún más el manejo de excepciones para la obtención de pronósticos por @autoSteve
- Reemplazar excepción con una advertencia #74 de @autoSteve
- Reintentar una carga de datos inicial/caché inexplicable por @autoSteve
- Registro de depuración menos ruidoso por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.36...v4.0.37

versión 4.0.36

- (Mejora) Atributos de sensor adicionales (estimación/estimación10/estimación90) y mejoras de registro por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.35...v4.0.36

versión 4.0.35

- (Mejora) Desglose del pronóstico de potencia y tiempo de cada sitio como atributos por @autoSteve
- No registre la actualización de la versión de opciones si @autoSteve no requiere ninguna actualización
- Agregar información sobre cómo preservar el historial y la configuración de Oziee al banner por @iainfogg

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.34...v4.0.35

versión 4.0.34

- Arreglar query_forecast_data para que @isorin devuelva pronósticos históricos a corto plazo
- Regresa instantáneamente a la memoria caché al recargar si fallan las llamadas a la API de uso/techo, lo que puede reducir el tiempo de inicio por @autoSteve
- Un tiempo de espera de llamada asincrónica de sitios obtenidos volverá al caché si existe por @autoSteve
- Muchas mejoras de registro por @autoSteve
- El caché de sitios a veces se crea incorrectamente con la clave API adjunta, a pesar de tener solo una clave API por @autoSteve
- Redacción de latitud y longitud en los registros de depuración por @autoSteve
- Posible eliminación de las advertencias de 'tally' por parte de @autoSteve
- Corrección del mecanismo de reintento del uso de la API por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.33...v4.0.34

versión 4.0.33

- Mejoras de rendimiento para las actualizaciones de sensores de @isorin, que incluyen:
    - Se redujo el intervalo de actualización de los sensores a 5 minutos.
    - Divida los sensores en dos grupos: sensores que necesitan actualizarse cada 5 minutos y sensores que necesitan actualizarse solo cuando se actualizan los datos o cambia la fecha (valores diarios)
    - Se solucionaron problemas con la eliminación de pronósticos anteriores (de más de 2 años), código roto
    - Se mejoró la funcionalidad de los pronósticos. Por ejemplo, "forecast_remaining_today" se actualiza cada 5 minutos calculando la energía restante del intervalo actual de 30 minutos. Lo mismo ocurre con los sensores de "hora actual/próxima hora".
- Redacción de la clave API de Solcast en los registros por @isorin
- Revertir Oziee '4.0.23' async_update_options #54 de @autoSteve, que estaba causando problemas de actualización de amortiguación

Comentario de @isorin: " *Utilizo el pronóstico restante de hoy para determinar la hora del día en que debo empezar a cargar las baterías para que alcancen una carga predeterminada por la noche. Con mis cambios, esto es posible".*

A eso yo le digo, muy bien hecho.

Nuevos colaboradores

- @isorin hizo su primera contribución en https://github.com/BJReplay/ha-solcast-solar/pull/45

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.32...v4.0.33

versión 4.0.32

- Corrección de errores: Contador de uso de API independiente para cada cuenta de Solcast por @autoSteve
- Corrección de errores: forzar todos los cachés a /config/ para todas las plataformas (corrige las implementaciones de Docker) #43 por @autoSteve
- Mejora de la depuración, información y opciones de advertencia del registro de obtención/reintento de pronósticos por @autoSteve
- Supresión de recuperaciones de pronósticos consecutivos en quince minutos (corrige recuperaciones múltiples extrañas si ocurre un reinicio exactamente cuando se activa la automatización para la recuperación) por @autoSteve
- Solución alternativa: evitar errores cuando "tally" no está disponible durante el reintento por #autoSteve
- Corrección para versiones anteriores de HA que no reconocen version= para async_update_entry() #40 por autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.0.32

versión 4.0.31

- docs: Cambios en README.md
- docs: Agregar notas de solución de problemas.
- docs: Combinar notas de cambios de info.md en README.md
- docs: Configurar para que HACS muestre README.md

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.30...v4.0.31

versión 4.0.30

- Corrección de errores: Compatibilidad con el almacenamiento en caché de múltiples sitios de cuentas Solcast
- Corrección de errores: el mecanismo de reintento cuando los sitios de la azotea se reúnen con éxito estaba dañado.

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.29...v4.0.30

versión 4.0.29

- Corrección de errores: escribir caché de uso de API en cada encuesta exitosa por @autoSteve en https://github.com/BJReplay/ha-solcast-solar/pull/29
- Corrección de errores: límite de API predeterminado a 10 para hacer frente a la falla de llamada inicial por @autoSteve
- Aumentar los reintentos GET de los sitios de dos a tres por @autoSteve

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.28...v4.0.29

versión 4.0.28

- Agregar reintento para la colección de sitios en azoteas n.° 12 por @autoSteve en https://github.com/BJReplay/ha-solcast-solar/pull/26
- Cambios completos en info.md desde la versión v4.0.25
- Reincorporar la mayoría de los cambios de oziee v4.0.23 por @autoSteve
- Conservar datos en caché cuando se alcanza el límite de API

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.27...v4.0.28

Nuevo colaborador

- @autoSteve ha hecho una gran contribución en los últimos días: ¡tiene un botón de patrocinador en su perfil, así que no tengas miedo de usarlo!

versión 4.0.27

- documentación: Actualización de info.md por @Kolbi en https://github.com/BJReplay/ha-solcast-solar/pull/19
- Utilice aiofiles con apertura asíncrona, espere data_file por @autoSteve en https://github.com/BJReplay/ha-solcast-solar/pull/21
- Agregue soporte para async_get_time_zone() por @autoSteve en https://github.com/BJReplay/ha-solcast-solar/pull/25

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.26...v4.0.27

Nuevos colaboradores

- @Kolbi hizo su primera contribución en https://github.com/BJReplay/ha-solcast-solar/pull/19
- @autoSteve hizo su primera contribución en https://github.com/BJReplay/ha-solcast-solar/pull/21

versión 4.0.26

- Corrige los problemas n.° 8, n.° 9 y n.° 10: Mi categoría de botón HA por @mZ738 en https://github.com/BJReplay/ha-solcast-solar/pull/11
- Actualización de README.md de @wimdebruyn en https://github.com/BJReplay/ha-solcast-solar/pull/5
- Prepárese para el nuevo lanzamiento de @BJReplay en https://github.com/BJReplay/ha-solcast-solar/pull/13

Registro de cambios completo: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.25...v4.0.26

Nuevos colaboradores

- @mZ738 hizo su primera contribución en https://github.com/BJReplay/ha-solcast-solar/pull/11
- @wimdebruyn hizo su primera contribución en https://github.com/BJReplay/ha-solcast-solar/pull/5

versión 4.0.25

- Presentación de HACS

versión 4.0.24

- Más cambios para eliminar enlaces a https://github.com/oziee que se pasaron por alto la primera vez
- Más cambios para prepararse para enviar a HACS

versión 4.0.23

- Cambió de propietario a @BJReplay
- Se cambió el repositorio de Github a https://github.com/BJReplay/ha-solcast-solar

versión 4.0.22

- Esta vez el sensor meteorológico ha desaparecido... y el reinicio a medianoche UTC funciona.
- (*)Se agregó una configuración para establecer un límite estricto para inversores con paneles solares de gran tamaño. *El 99,9999999 % de los usuarios no necesitarán usar y configurar esto nunca (el 0,00000001 % es @CarrapiettM)

versión 4.0.21

- Se eliminó el sensor meteorológico porque sigue fallando con errores.

versión 4.0.20

- Se corrigió el error de información para `solcast_pv_forecast_forecast_today (<class 'custom_components.solcast_solar.sensor.SolcastSensor'>) is using state class 'measurement' which is impossible considering device class ('energy')`
- Se eliminó la obtención de UTC de medianoche y se reemplazó con establecer en cero para reducir el sondeo en el sistema Solcast ⚠️ Para ayudar a reducir el impacto en el backend de Solcast, Solcast solicitó que los usuarios configuren sus automatizaciones para sondear con un tiempo mínimo y segundo aleatorio. Si está sondeando, por ejemplo, a las 10:00, configúrelo a las 10:04:10, por ejemplo, para que no todos estén sondeando los servicios al mismo tiempo.

versión 4.0.19

- Se soluciona el problema de restablecer el límite/uso de la API sin actualizar la interfaz de usuario de HA.

versión 4.0.18

- El valor del sensor meteorológico fijo no persiste
- Restablecer el límite de la API y los sensores de uso a la medianoche UTC (restablecer uso)

versión 4.0.17

- Traducción al eslovaco actualizada gracias @misa1515
- Se agregó un sensor para la descripción meteorológica de Solcast.

versión 4.0.16

- @Zachoz agregó la idea de agregar una configuración para seleccionar qué valor de campo de estimación solcast para los cálculos de pronóstico, ya sea estimación, estimación10 o estimación90 ESTIMATE - Pronósticos predeterminados ESTIMATE10 = Pronósticos 10 - escenario más nublado de lo esperado
     ESTIMATE90 = Pronóstico 90 - escenario menos nublado de lo esperado

versión 4.0.15

- Se agregó un sensor personalizado "Próximas X horas". Seleccione el número de horas que se calcularán según el sensor.
- Se agregó traducción al francés gracias a @Dackara
- Se agregaron algunos sensores para incluirlos en los datos de estadísticas de HA

versión 4.0.14

- Se cambiaron los valores de los atributos de los sitios en la azotea para que los pines no se agreguen a los mapas (HA agrega automáticamente el elemento al mapa si los atributos contienen valores de latitud y longitud)
- Se agregó urdu gracias a @yousaf465

versión 4.0.13

- Se agregó la traducción al eslovaco gracias a @misa1515
- Se extendió el tiempo de espera de conexión de sondeo de 60 a 120 segundos.
- Se agregaron algunos puntos de salida de depuración adicionales para la verificación de datos.
- El nuevo atributo de datos de pronóstico `dataCorrect` devuelve Verdadero o Falso si los datos están completos para ese día.
- Se eliminaron `0 of 48` mensajes de depuración para el pronóstico del séptimo día porque si la API no se sondea a la medianoche, los datos no están completos para el séptimo día (limitación de los registros máximos que devuelve Solcast)

versión 4.0.12

- La versión beta de HA 2023.11 obliga a que los sensores no aparezcan en la `Configuration` . Los sensores de techo se han trasladado a `Diagnostic`

versión 4.0.11

- Mejor manejo cuando faltan piezas de datos para algunos sensores

versión 4.0.10

- Correcciones para cambiar la clave API una vez que se ha configurado una previamente

versión 4.0.9

- Nuevo servicio para actualizar los factores de amortiguación previstos por hora

versión 4.0.8

- Se agregó la traducción al polaco gracias a @home409ca
- Se agregó nueva `Dampening` a la configuración de integración de Solcast

versión 4.0.7

- Mejor manejo cuando el sitio Solcast no devuelve correctamente los datos de la API

versión 4.0.6

- Se corrigieron errores de división por cero si no se devolvían datos
- Valor de pronóstico fijo restante para hoy. Ahora incluye el pronóstico del bloque actual de 30 minutos en el cálculo.

versión 4.0.5

- PR #192 - Traducción al alemán actualizada. Gracias @florie1706
- Se arregló el pronóstico `Remaining Today` ... ahora también utiliza datos de intervalos de 30 minutos
- Se corrigió que `Download diagnostic` arrojara un error al hacer clic

versión 4.0.4

- Finalizó la llamada de servicio `query_forecast_data` para consultar los datos de pronóstico. Devuelve una lista de datos de pronóstico con un rango de fecha y hora de inicio a fin.
- y eso es todo... a menos que HA haga cambios importantes o haya un error importante en v4.0.4, esta es la última actualización

versión 4.0.3

- Se actualizó el alemán gracias a @florie1706 PR#179 y se eliminaron todos los demás archivos de localización.
- Se agregó el nuevo atributo `detailedHourly` a cada sensor de pronóstico diario que enumera los pronósticos por hora en kWh.
- Si faltan datos, los sensores seguirán mostrando algo, pero un registro de depuración indicará que al sensor le faltan datos.

versión 4.0.2

- ¡Los nombres de los sensores **han** cambiado! Esto se debe a las cadenas de localización de la integración.
- La precisión decimal se modificó para el pronóstico de mañana de 0 a 2
- Se corrigieron los datos faltantes del pronóstico del séptimo día que se ignoraban.
- Se agregó nuevo sensor `Power Now`
- Se agregó un nuevo sensor `Power Next 30 Mins`
- Se agregó un nuevo sensor `Power Next Hour`
- Se agregó localización para todos los objetos en la integración. Gracias a @ViPeR5000 por ayudarme a empezar a pensar en esto (se usó Google Translate, si encuentra algo incorrecto, envíeme un mensaje privado y puedo actualizar las traducciones).

versión 4.0.1

- rebasado desde 3.0.55
- Mantiene los últimos 730 días (2 años) de datos de pronóstico
- Algunos sensores han actualizado su clase de dispositivo y unidad de medida nativa a un tipo correcto
- El recuento de sondeo de API se lee directamente desde Solcast y ya no se calcula
- Se acabó el sondeo automático... ahora cada uno puede crear una automatización para sondear los datos cuando quiera. Esto se debe a que muchos usuarios ahora solo tienen 10 llamadas a la API al día.
- Eliminado el guardado del cambio de hora UTC y manteniendo los datos de solcast tal como están para que los datos de zona horaria se puedan cambiar cuando sea necesario
- Los elementos del historial desaparecieron debido al cambio de nombre del sensor. Ya no se utiliza el historial de HA y, en su lugar, solo se almacenan los datos en el archivo solcast.json
- Se eliminó la actualización del servicio actual. Los datos reales de solcast ya no se sondean (se usan en la primera instalación para obtener datos anteriores para que la integración funcione y no recibo informes de problemas porque solcast no brinda datos del día completo, solo datos de cuando llama)
- Muchos de los mensajes de registro se han actualizado para que sean de depuración, información, advertencia o errores.
- **Es** posible que algunos sensores ya no tengan valores de atributos adicionales o que los valores de los atributos hayan cambiado de nombre o se hayan modificado los datos almacenados en ellos.
- Datos de diagnóstico más detallados para compartir cuando sea necesario para ayudar a depurar cualquier problema
- Parte del trabajo de @rany2 ya se ha integrado

Eliminado 3.1.x

- Demasiados usuarios no pudieron soportar la potencia de esta versión.
- v4.xx reemplaza 3.0.55 - 3.1.x con nuevos cambios

versión 3.0.47

- Se agregó el atributo de nombre de día de la semana para los pronósticos del sensor, hoy, mañana, D3..7 pueden leer los nombres a través de la plantilla {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_today', 'dayname') }} {{ state_attr('sensor.solcast_forecast_tomorrow', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D3', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D4', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D5', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D6', 'dayname') }} {{ state_attr('sensor.solcast_forecast_D7', 'nombre del día')

versión 3.0.46

- Posible problema con Maria DB: posible solución

versión 3.0.45

- prelanzamiento
- Actualmente en prueba
- No hará daño a nadie si lo instalas

versión 3.0.44

- prelanzamiento
- mejores datos de diagnóstico
- Sólo para probar
- No hará daño a nadie si lo instalas

versión 3.0.43

- ¡Prelanzamiento no apto para uso!
- no instalar :) solo para probar

versión 3.0.42

- Se solucionó el problema de usar el servicio para actualizar los pronósticos llamando dos veces.

versión 3.0.41

- Registro recodificado. Reformulado. Más depuración vs. información vs. registro de errores.
- El contador de uso de API no se registró cuando se restableció a cero a la medianoche UTC
- Se agregó un nuevo servicio donde puedes llamar para actualizar los datos reales de Solcast para los pronósticos.
- Se agregó la información de la versión a la interfaz de integración.

versión 3.0.40

- Alguien dejó un código sin usar en 3.0.39, lo que causa problemas.

versión 3.0.39

- información de la versión eliminada

versión 3.0.38

- Error con la corrección v3.0.37 para actualizar los sensores

versión 3.0.37

- Asegúrese de que los sensores por hora se actualicen cuando el sondeo automático esté deshabilitado.

versión 3.0.36

- Incluye todos los artículos previos al lanzamiento.
- Los datos reales pasados precisos ahora están configurados para sondear la API solo al mediodía y a última hora del día (es decir, solo dos veces al día).

v3.0.35 - PRE LANZAMIENTO

- Extendió el tiempo de espera de la conexión a Internet a 60 segundos

v3.0.34 - PRE LANZAMIENTO

- Se agregó un servicio para borrar el antiguo archivo solcast.json para tener un inicio limpio.
- Devuelve datos de gráficos de energía vacíos si hay un error al generar información

versión 3.0.33

- Se agregaron sensores para los días de pronóstico 3, 4, 5, 6 y 7.

versión 3.0.32

- Requisitos de llamada a la función de configuración de HA refactorizados
- Refactoricé otro código con errores tipográficos para escribir las palabras correctamente... no es gran cosa.

versión 3.0.30

- fusionado en algún trabajo de @696GrocuttT PR en este lanzamiento
- Código corregido relacionado con el uso de todos los recuentos de API permitidos
- Es muy probable que esta versión estropee el contador API actual, pero después de que se restablezca el contador UTC, todo volverá a estar bien en el mundo del conteo API.

versión 3.0.29

- Se cambió el sensor Hora pico hoy/mañana de fecha y hora a hora
- Se cambió nuevamente la unidad para la medición de pico a Wh, ya que el sensor indica el pronóstico generado por las horas pico/máximas para la hora.
- Se agregó una nueva opción de configuración para la integración que permite desactivar el sondeo automático. Los usuarios pueden configurar su propia automatización para sondear datos cuando lo deseen (principalmente debido a que Solcast ha cambiado la asignación de API para nuevas cuentas a solo 10 al día).
- El sensor del contador API ahora muestra el total utilizado en lugar de la asignación restante, ya que algunos tienen 10 y otros 50. Se mostrará "Asignación API excedida" si no le queda ninguna.

versión 3.0.27

- Cambié la unidad para la medición del pico #86 gracias Ivesvdf
- Algunos otros cambios menores de texto para los registros
- Se modificó la llamada de servicio gracias 696GrocuttT
- Incluye solución para el problema n.° 83

versión 3.0.26

- Prueba de corrección para el problema n.° 83

versión 3.0.25

- Se eliminó el PR para 3.0.24: causó errores en el gráfico de pronóstico
- Se solucionó el problema de HA 2022.11: no se puede agregar el pronóstico al panel solar.

versión 3.0.24

- Relaciones públicas fusionadas de @696GrocuttT

versión 3.0.23

- Se agregó más código de registro de depuración
- Se agregó el servicio para actualizar el pronóstico.

versión 3.0.22

- Se agregó más código de registro de depuración

versión 3.0.21

- Se agregaron más registros de depuración para mayor información.

versión 3.0.19

- REVISIÓN: coordinador.py", línea 133, en update_forecast para update_callback en self._listeners: RuntimeError: el diccionario cambió de tamaño durante la iteración
- Esta versión necesita HA 2022.7+ ahora

versión 3.0.18

- Se modificaron los cálculos del valor de retorno del contador de API

versión 3.0.17

- Establezca el tiempo de sondeo de la API a 10 minutos después de la hora para darle tiempo a la API de Solcast para calcular los datos satelitales.

versión 3.0.16

- Se corrigió el sondeo de API para obtener datos reales de vez en cuando durante el día.
- Se agregó la ruta completa al archivo de datos - gracias OmenWild

versión 3.0.15

- Funciona tanto en la versión beta 2022.6 como en la 2022.7.

versión 3.0.14

- Corrige errores de HA 2022.7.0b2 (parece :) )

versión 3.0.13

- Los datos graficados anteriores no se reiniciaron a la medianoche, hora local.
- Falta la importación de Asyncio

versión 3.0.12

- Los datos graficados para la semana/mes/año no estaban ordenados, por lo que el gráfico estaba desordenado.

versión 3.0.11

- Se agregó tiempo de espera para las conexiones del servidor API de Solcast.
- Se agregaron datos gráficos de los últimos 7 días al panel de energía (solo funciona si está registrando datos)

versión 3.0.9

- **Los usuarios que actualicen desde v3.0.5 o anterior deben eliminar el archivo 'solcast.json' en el directorio HA&gt;config para detener cualquier error**
- Se renombraron los sensores con el prefijo "solcast_" para facilitar su nombramiento.
- ** obtendrá duplicaciones de los sensores en la integración debido al cambio de nombre. Estos se mostrarán en gris en la lista o con valores como desconocido o no disponible, etc. simplemente elimine estos sensores antiguos uno por uno de la integración **

versión 3.0.6

- **Los usuarios que actualicen desde v3.0.x deben eliminar el archivo 'solcast.json' en el directorio HA&gt;config**
- Se corrigieron muchos pequeños errores y problemas.
- Se agregó la capacidad de agregar múltiples cuentas Solcast. Simplemente separe las claves API con comas en la configuración de integración.
- Contador de API restante a API izquierda. muestra cuánto queda en lugar del recuento usado.
- Los datos de "pronóstico actual" ahora solo se llaman una vez: la última llamada a la API al atardecer o durante la primera ejecución de la instalación de la integración.
- Los datos de pronóstico se siguen consultando cada hora entre el amanecer y el atardecer, y una vez a medianoche todos los días. *Simplemente elimine el antiguo sensor del contador API, ya que ya no se utiliza.*

versión beta v3.0.5

- Se corrigieron los valores de los sensores 'esta hora' y 'próxima hora'.
- ralentizar el sondeo de la API si hay más de una azotea para sondear.
- Arreglar los datos del gráfico de la primera hora.
- ¿Posiblemente RC1?? ya veremos.

versión beta v3.0.4

- Corrección de errores.

versión 3.0

- reescritura completa

La historia anterior no está disponible.




## Créditos

Modificado de las grandes obras de

- oziee/ha-solcast-solar
- @rany2 - ranygh@riseup.net
- dannerph/homeassistant-solcast
- cjtapper/solcast-py
- home-assistant-libs/forecast_solar
