# Cómo colaborar

Gracias por querer mejorar ClutchReel. Toda ayuda cuenta: avisar de un fallo, proponer una idea, mejorar la documentación o enviar código.

## Avisar de un fallo o proponer una idea

Abre un *issue* con la plantilla que corresponda. Para un fallo, lo más útil es:

- qué hiciste y qué esperabas que pasara;
- qué pasó (el mensaje exacto de error, si hay);
- versión de ClutchReel (abajo a la izquierda en la app), de Windows, de OBS y de CS2;
- el informe de errores (`Ajustes → Ver registro → Copiar informe de errores`).

Antes de pegar el informe, **revísalo**: puede incluir nombres de jugadores de tus demos y rutas de tu PC (por ejemplo `C:\Users\tu-nombre`). Tacha lo que no quieras publicar. Las contraseñas ya salen tachadas.

Si el fallo es de seguridad, no abras un issue público: sigue [`SECURITY.md`](SECURITY.md).

## Enviar cambios

1. Haz un *fork* y crea una rama para tu cambio.
2. Prepara el entorno: ejecuta `Iniciar.bat` una vez y después `.venv\Scripts\pip install -r requirements-dev.txt`.
3. Antes de enviar, comprueba que todo pasa:
   ```
   .venv\Scripts\python -m pytest
   .venv\Scripts\python -m ruff check .
   .venv\Scripts\python -m mypy clutchreel
   ```
4. Añade un test para cada fallo que corrijas y actualiza el README si cambia algo que vea el usuario.
5. Abre un *pull request* explicando qué cambia y cómo lo has probado (sobre todo si toca la grabación con OBS y CS2, que los tests simulan).

Normas que sigue el proyecto:

- La interfaz y los mensajes están en español, en un tono claro y directo.
- ClutchReel nunca inyecta código en el juego, no lee su memoria ni modifica sus archivos: solo usa el visor de demos con comandos de consola normales y graba con OBS. No se aceptan cambios que salgan de ahí.
- Los colores y estilos de la interfaz viven en `clutchreel/ui/theme.py`.
- No se añaden dependencias con licencia GPL o AGPL (ClutchReel es MIT).
- No se suben demos, vídeos ni datos de jugadores reales: usa datos sintéticos en los tests.

## Licencia de las contribuciones

ClutchReel se distribuye bajo la [licencia MIT](LICENSE). Al enviar una contribución aceptas que se publique bajo esa misma licencia y confirmas que tienes derecho a hacerlo (que el código es tuyo o compatible con MIT).
