# Actualización SAP Integration 15.6.15

Esta guía describe cómo probar y desplegar la versión `15.6.15` del conector
SAP Integration, así como regresar a la rama anterior si fuera necesario.

## Alcance de la actualización

La actualización incorpora protecciones para:

- Evitar recrear documentos SAP cancelados.
- Procesar cancelaciones dentro de la compañía correspondiente.
- Evitar movimientos parciales de inventario cuando falla el documento principal.
- No avanzar el delta cuando los procesadores transaccionales migrados reportan
  un resultado incompleto.
- Cerrar correctamente las sesiones SAP ante errores de conexión.
- Limitar las excepciones de fecha de vencimiento a facturas importadas desde SAP.

También agrega al mapeo de órdenes de venta:

```text
CancelStatus → CancelStatus
Nivel: head
Tipo: map
```

Esta fila no crea un campo nuevo en `Sales Order`. Se utiliza para incluir
`CancelStatus` en la consulta a SAP y evitar importar órdenes canceladas como
documentos activos.

## Preparación

Antes de cambiar la rama, crear un respaldo y detener temporalmente el
scheduler para impedir que una sincronización comience durante el despliegue:

```bash
cd /home/frappe/yaesta
bench --site <sitio-productivo> backup --with-files
bench --site <sitio-productivo> disable-scheduler
```

Confirmar que `SAP Credentials` contiene una fila para cada compañía utilizada
por el conector. El nombre debe coincidir exactamente con el registrado en
ERPNext y en los mapeos.

## Activar la rama de actualización

```bash
cd /home/frappe/yaesta/apps/sap_integration
git switch fix/sap-integration-auditoria-2026-10-30
```

## Configuración opcional

Los siguientes valores pueden agregarse al archivo `site_config.json` del sitio:

```json
{
  "sap_request_timeout": 60,
  "sap_max_pages": 10000,
  "sap_verify_ssl": 0
}
```

Descripción:

- `sap_request_timeout`: tiempo máximo de lectura de una solicitud SAP, en
  segundos. El tiempo de conexión se mantiene en 10 segundos.
- `sap_max_pages`: cantidad máxima de páginas permitidas en una sincronización.
  Protege contra paginaciones repetidas o sin fin.
- `sap_verify_ssl`: usa `1` para validar el certificado HTTPS de SAP y `0` para
  conservar el comportamiento actual sin validación.

Estos parámetros son opcionales. Si no se configuran, se utilizan los valores
mostrados anteriormente.

También pueden establecerse mediante Bench:

```bash
bench --site <sitio-productivo> set-config sap_request_timeout 60
bench --site <sitio-productivo> set-config sap_max_pages 10000
bench --site <sitio-productivo> set-config sap_verify_ssl 0
```

Antes de usar `sap_verify_ssl = 1`, comprobar que el certificado del SAP
Service Layer sea válido y que su autoridad certificadora sea confiable para el
servidor de Frappe.

## Aplicar la actualización

```bash
cd /home/frappe/yaesta
bench --site <sitio-productivo> migrate
bench --site <sitio-productivo> clear-cache
bench restart
```

No se agregaron dependencias de Python o JavaScript, por lo que no es necesario
ejecutar `bench build` ni instalar paquetes adicionales.

`bench migrate` importa los fixtures del conector, incluido el mapeo
`CancelStatus`. También puede reemplazar cambios realizados manualmente sobre
otros mapeos incluidos como fixtures; por eso el respaldo previo es obligatorio.

## Validación previa al scheduler

Antes de reactivar las tareas programadas:

1. Probar la conexión SAP de cada compañía desde `SAP Credentials`.
2. Confirmar que `Mapeo Orden De Venta SAP` contiene `CancelStatus` en nivel
   `head` y con tipo `map`.
3. Revisar que las compañías y endpoints del resto de mapeos permanezcan
   correctos.
4. Ejecutar una sincronización controlada y revisar los logs antes de habilitar
   todos los trabajos automáticos.

Después de validar:

```bash
bench --site <sitio-productivo> enable-scheduler
```

## Regresar a la rama anterior

```bash
cd /home/frappe/yaesta
bench --site <sitio-productivo> disable-scheduler

cd /home/frappe/yaesta/apps/sap_integration
git switch develop

cd /home/frappe/yaesta
bench --site <sitio-productivo> migrate
bench --site <sitio-productivo> clear-cache
bench restart
bench --site <sitio-productivo> enable-scheduler
```

Cambiar de rama revierte el código y los fixtures, pero no elimina documentos o
movimientos que una sincronización ya haya creado. Si se necesita revertir
también los datos generados durante la prueba, se debe restaurar el respaldo o
cancelar los documentos mediante el procedimiento contable correspondiente.
