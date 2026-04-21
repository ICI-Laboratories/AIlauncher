# Update Workflow

## Idea clave

El codigo fuente vive en tu maquina local. El servidor no es la fuente de
verdad; el servidor solo ejecuta una copia desplegada del proyecto.

Eso significa:

- cambios de codigo -> se hacen en local, se prueban en local y luego se
  despliegan al servidor
- cambios de configuracion del servicio -> normalmente se hacen en el servidor
- cambios de modelos o catalogo -> idealmente se hacen en el repo local y se
  redeployan

## Layout actual del servidor

- codigo desplegado: `/opt/ailauncher/app`
- entorno virtual: `/opt/ailauncher/venv`
- servicio systemd: `/etc/systemd/system/ailauncher.service`
- variables sensibles: `/etc/ailauncher/ailauncher.env`
- helper de salud: `/usr/local/bin/ailauncher-check`
- logs de requests: `/var/log/ailauncher/requests.jsonl`
- modelos de Ollama: `/srv/ai-data/ollama/models`
- backups de app: `/srv/ai-data/ailauncher/archive`

## Flujo recomendado

1. Haces cambios en local.
2. Corres pruebas locales.
3. Ejecutas el script de despliegue.
4. El script:
   - empaqueta el repo
   - sube un release temporal al servidor
   - guarda un backup del app actual
   - reemplaza `/opt/ailauncher/app`
   - reinstala el paquete en `/opt/ailauncher/venv`
   - reinicia `ailauncher`
   - valida salud del servicio

## Script de despliegue

Desde la raiz del repo:

```bash
python scripts/deploy_server.py --host 200.94.30.218 --user administrador --port 222
```

En Windows tambien funciona:

```powershell
python .\scripts\deploy_server.py --host 200.94.30.218 --user administrador --port 222
```

Requisitos locales:

- `python`
- `ssh`
- `scp`

## Autenticacion

El script no guarda contrasenas. Usa la autenticacion normal de `ssh`/`scp`.

Recomendado:

- configurar llave SSH
- usar `ssh-agent`

Si sigues usando password, el script te pedira la autenticacion del login y,
si hace falta, la de `sudo`.

## Cuando NO basta con redeploy

### Solo cambias codigo Python o docs del app

Redeploy normal.

### Cambias el catalogo de modelos

Edita `deploy/models.server.json` en local y redeploy.

### Cambias variables del servicio

Eso vive en:

- `/etc/ailauncher/ailauncher.env`

Despues de cambiarlo:

```bash
sudo systemctl restart ailauncher
```

### Cambias hardening o puertos del servicio

Eso vive en:

- `/etc/systemd/system/ailauncher.service`

Despues:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ailauncher
```

## Verificacion rapida en el servidor

```bash
sudo systemctl status ailauncher
sudo /usr/local/bin/ailauncher-check
tail -n 20 /var/log/ailauncher/requests.jsonl
```

## Emergencias

Si editas algo directo en el servidor para salir del paso:

1. documenta lo que cambiaste
2. replica ese cambio en tu repo local
3. vuelve a desplegar desde local

Si no haces eso, tarde o temprano el siguiente deploy va a sobrescribir el
parche manual.

## Rollback

Cada deploy guarda un backup del app en:

- `/srv/ai-data/ailauncher/archive`

Si una version sale mal, puedes restaurar un backup anterior y reinstalarlo en
el `venv`.
