# The Tower

Climb 50 stories of ghosts, lava pools and flamethrowers. One touch and the run is over.

**Play in the browser:** https://yunks128.github.io/the-tower/

## Controls

| Key | Action |
| --- | --- |
| Left / Right | move |
| Up | jump |
| Space | swing the sword or fire the laser gun |
| Q | swap weapons |
| P | pause |

## Run on your computer

```
pip install -r requirements.txt
python tower.py
```

## Rebuild the browser version

The `docs/` folder is the web build served by GitHub Pages. To rebuild it after changing `tower.py`:

```
pip install pygbag
mkdir -p /tmp/web/the-tower && cp tower.py /tmp/web/the-tower/main.py
python -m pygbag --build --title "The Tower" /tmp/web/the-tower
cp /tmp/web/the-tower/build/web/* docs/
```
