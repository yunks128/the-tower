"""The Tower - climb 50 stories of ghosts, lava pools and flamethrowers.

Controls
    Left / Right arrows   move
    Up arrow              jump
    Space                 attack with the equipped weapon
    Q                     swap between weapons you own
    P or Esc              pause
"""
import asyncio
import json
import math
import os
import random
import sys

import pygame

WEB = sys.platform == "emscripten"     # running in a browser through pygbag

W, H = 960, 600
FPS = 60
CEIL_Y = 70            # bottom edge of the ceiling / HUD strip
FLOOR_Y = 500          # top edge of the floor
TOP_STORY = 50

PW, PH = 28, 44        # player size
SPEED = 250
JUMP = 560
GRAVITY = 1500

SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores.json")
GHOST_POINTS = 10
STORY_POINTS = 50
SCORE_KEY = "the-tower-scores"       # browser localStorage key used instead of the file

ROCK_W = 46
LAVA_DEPTH = 20        # how far below the floor the lava surface sits
FLAME_PERIOD = 2.0     # a flamethrower fires once every 2 seconds
FLAME_ON = 0.7         # ...and each burst lasts this long
FLAME_WARN = 0.4       # nozzle glows this long before a burst

LEN_COSTS = [25, 50, 90, 140]
SWORD_DMG = [2, 3, 5, 7, 10, 14]
DMG_COSTS = [30, 60, 110, 170, 250]
DOUBLE_COST = 80
GUNS = {
    "pistol": dict(name="Laser Pistol", cost=90, dmg=3, cooldown=0.8, color=(90, 255, 140)),
    "rifle": dict(name="Laser Rifle", cost=260, dmg=6, cooldown=0.5, color=(255, 90, 220)),
}
SWING_TIME = 0.2
SWING_COOLDOWN = 0.38


def story_rules(story):
    """Return (ghost count, has lava pool, has flamethrower) for a story."""
    if story < 10:
        return random.randint(2, 3), random.random() < 0.35, False
    if story <= 20:
        return 3, random.random() < 0.25, True
    return random.randint(1, 5), random.random() < 0.40, random.random() < 0.50


class Player:
    def __init__(self):
        self.len_lvl = 0
        self.dmg_lvl = 0
        self.double = False
        self.guns = []
        self.weapon = "sword"
        self.place(40)

    def place(self, x):
        self.x, self.y = float(x), float(FLOOR_Y - PH)
        self.vy = 0.0
        self.facing = 1
        self.on_ground = True
        self.moving = False
        self.cooldown = 0.0
        self.swing = 0.0
        self.swing_hits = []

    @property
    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), PW, PH)

    @property
    def blade(self):
        return 30 + 16 * self.len_lvl

    def sword_box(self):
        reach = self.blade + 14
        r = self.rect
        x = r.centerx if self.facing > 0 else r.centerx - reach
        return pygame.Rect(x, r.top - 24, reach, PH + 32)

    def move(self, dx, dy, solids):
        self.x += dx
        for s in solids:
            if self.rect.colliderect(s):
                if dx > 0:
                    self.x = s.left - PW
                elif dx < 0:
                    self.x = s.right
        self.x = max(0, min(W - PW, self.x))

        self.y += dy
        for s in solids:
            if self.rect.colliderect(s):
                if dy > 0:
                    self.y = s.top - PH
                elif dy < 0:
                    self.y = s.bottom
                self.vy = 0
        self.on_ground = False
        if self.vy >= 0:
            probe = self.rect.move(0, 1)
            for s in solids:
                if probe.colliderect(s):
                    self.on_ground = True
                    self.vy = 0
                    self.y = s.top - PH
                    break


class Ghost:
    W, H = 36, 42

    def __init__(self, x, y, story):
        self.x, self.y = float(x), float(y)
        self.hp = self.max_hp = 2 + story // 4
        self.speed = min(55 + story * 1.6, 135)
        self.phase = random.uniform(0, math.tau)
        self.spawn = 1.2      # fades in, harmless until this runs out
        self.flash = 0.0
        self.kb = 0.0

    @property
    def rect(self):
        return pygame.Rect(round(self.x - self.W / 2), round(self.y - self.H / 2), self.W, self.H)


class Level:
    def __init__(self, story):
        self.story = story
        n_ghosts, has_lava, has_flame = story_rules(story)
        self.pool = None
        self.rocks = []
        self.flame_x = None
        self.flame_t = 0.0

        if has_lava:
            w = random.choice((300, 340, 380))
            if not has_flame:
                px = random.randint(220, 780 - w)
            elif random.random() < 0.5:
                px = random.randint(190, 230)
                self.flame_x = random.randint(px + w + 70, 800)
            else:
                self.flame_x = random.randint(190, 260)
                px = random.randint(self.flame_x + 70, 800 - w)
            self.pool = pygame.Rect(px, FLOOR_Y, w, H - FLOOR_Y)
            n = 3 if w >= 380 else 2
            gap = (w - n * ROCK_W) / (n + 1)
            for i in range(n):
                top = FLOOR_Y - random.choice((0, 8, 16))
                rx = round(px + gap * (i + 1) + ROCK_W * i)
                self.rocks.append(pygame.Rect(rx, top, ROCK_W, H - top))
        elif has_flame:
            self.flame_x = random.randint(250, 780)

        if self.pool:
            self.floors = [pygame.Rect(0, FLOOR_Y, self.pool.left, H - FLOOR_Y),
                           pygame.Rect(self.pool.right, FLOOR_Y, W - self.pool.right, H - FLOOR_Y)]
        else:
            self.floors = [pygame.Rect(0, FLOOR_Y, W, H - FLOOR_Y)]
        self.solids = self.floors + self.rocks

        self.door = pygame.Rect(W - 66, FLOOR_Y - 80, 46, 80)
        self.ghosts = [Ghost(random.randint(420, 880), random.randint(CEIL_Y + 60, FLOOR_Y - 80), story)
                       for _ in range(n_ghosts)]

    @property
    def flame_rect(self):
        return pygame.Rect(self.flame_x - 22, CEIL_Y + 36, 44, FLOOR_Y - CEIL_Y - 36)

    @property
    def flame_phase(self):
        """'on', 'warn' or 'off' - the burst comes at the end of each 2 second cycle."""
        t = self.flame_t % FLAME_PERIOD
        if t >= FLAME_PERIOD - FLAME_ON:
            return "on"
        if t >= FLAME_PERIOD - FLAME_ON - FLAME_WARN:
            return "warn"
        return "off"


def make_backdrop():
    rng = random.Random(7)
    s = pygame.Surface((W, H))
    s.fill((30, 27, 42))
    for row, y in enumerate(range(0, H, 24)):
        for x in range(-24 if row % 2 else 0, W, 48):
            d = rng.randint(-5, 5)
            pygame.draw.rect(s, (48 + d, 43 + d, 64 + d), (x + 1, y + 1, 46, 22), border_radius=2)
    return s


class Game:
    def __init__(self, screen):
        self.screen = screen
        self.backdrop = make_backdrop()
        self.fonts = {96: pygame.font.Font(None, 96)}
        self.time = 0.0
        self.state = "title"
        self.scores = self.load_scores()
        self.new_best = False
        self.new_run()

    # ---------------------------------------------------------------- setup

    def new_run(self):
        self.player = Player()
        self.story = 1
        self.coins = 0
        self.score = 0
        self.cause = ""
        self.start_story()

    def start_story(self):
        self.level = Level(self.story)
        self.player.place(40)
        self.lasers = []
        self.particles = []
        self.popups = []
        self.banner = 1.8
        self.paused = False
        self.shop_sel = 0
        self.shop_msg = ""

    def load_scores(self):
        try:
            if WEB:
                from platform import window
                data = json.loads(window.localStorage.getItem(SCORE_KEY) or "[]")
            else:
                with open(SCORE_FILE) as f:
                    data = json.load(f)
            return [(int(score), int(story)) for score, story in data]
        except Exception:
            return []

    def save_score(self):
        """Add this run to the saved top five."""
        self.new_best = self.score > max((s for s, _ in self.scores), default=0)
        self.scores = sorted(self.scores + [(self.score, self.story)], reverse=True)[:5]
        try:
            if WEB:
                from platform import window
                window.localStorage.setItem(SCORE_KEY, json.dumps(self.scores))
            else:
                with open(SCORE_FILE, "w") as f:
                    json.dump(self.scores, f)
        except Exception:
            pass

    def die(self, cause):
        r = self.player.rect
        self.burst(r.centerx, r.centery, (255, 140, 30), 30)
        self.cause = cause
        self.state = "dead"
        self.save_score()

    def next_story(self):
        self.story += 1
        self.start_story()
        self.state = "play"

    # ---------------------------------------------------------------- input

    def on_key(self, key):
        confirm = key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
        if self.state == "title":
            if confirm:
                self.state = "play"
        elif self.state == "play":
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.paused = not self.paused
            elif key == pygame.K_q and not self.paused:
                self.swap_weapon()
        elif self.state == "shop":
            items = self.shop_items()
            if key == pygame.K_UP:
                self.shop_sel = (self.shop_sel - 1) % len(items)
            elif key == pygame.K_DOWN:
                self.shop_sel = (self.shop_sel + 1) % len(items)
            elif confirm:
                self.shop_buy(items[self.shop_sel])
        elif self.state in ("dead", "win"):
            if confirm:
                self.new_run()
                self.state = "play"
            elif key in (pygame.K_ESCAPE, pygame.K_q):
                if WEB:                 # a browser tab can't be closed, so go back to the title
                    self.new_run()
                    self.state = "title"
                else:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))

    def swap_weapon(self):
        owned = ["sword"] + self.player.guns
        self.player.weapon = owned[(owned.index(self.player.weapon) + 1) % len(owned)]
        self.player.swing = 0

    # ----------------------------------------------------------------- shop

    def shop_items(self):
        """Rows of (label, status, cost, action, description). cost None = free."""
        p = self.player

        def bump(attr):
            return lambda: setattr(p, attr, getattr(p, attr) + 1)

        def equip(name):
            return lambda: setattr(p, "weapon", name)

        def buy_gun(name):
            def f():
                p.guns.append(name)
                p.weapon = name
            return f

        items = [(f"Climb to story {self.story + 1}", "", None, self.next_story,
                  "Take the stairs up to the next story.")]

        if p.len_lvl < len(LEN_COSTS):
            items.append(("Bigger sword", f"size {p.len_lvl + 1} > {p.len_lvl + 2}", LEN_COSTS[p.len_lvl],
                          bump("len_lvl"), "A longer blade reaches ghosts from further away."))
        else:
            items.append(("Bigger sword", "MAX", None, None, "Your sword is as big as it gets."))

        if p.dmg_lvl < len(DMG_COSTS):
            items.append(("Sharper sword", f"damage {SWORD_DMG[p.dmg_lvl]} > {SWORD_DMG[p.dmg_lvl + 1]}",
                          DMG_COSTS[p.dmg_lvl], bump("dmg_lvl"), "Each swing does more damage."))
        else:
            items.append(("Sharper sword", "MAX", None, None, "Your sword is as sharp as it gets."))

        if not p.double:
            items.append(("Double strike", "", DOUBLE_COST, lambda: setattr(p, "double", True),
                          "One swing can hit two ghosts at a time."))
        else:
            items.append(("Double strike", "OWNED", None, None, "One swing hits two ghosts at a time."))

        for key, gun in GUNS.items():
            info = f"Shoots ghosts from a distance. Damage {gun['dmg']}, {gun['cooldown']}s between shots."
            if key not in p.guns:
                items.append((gun["name"], "", gun["cost"], buy_gun(key), info))
            elif p.weapon == key:
                items.append((gun["name"], "EQUIPPED", None, None, info))
            else:
                items.append((gun["name"], "equip", None, equip(key), info))

        if p.guns:
            if p.weapon == "sword":
                items.append(("Sword", "EQUIPPED", None, None, "You can only use one weapon at a time."))
            else:
                items.append(("Sword", "equip", None, equip("sword"), "You can only use one weapon at a time."))
        return items

    def shop_buy(self, item):
        _, _, cost, action, _ = item
        self.shop_msg = ""
        if action is None:
            return
        if cost is not None:
            if cost > self.coins:
                self.shop_msg = "Not enough coins!"
                return
            self.coins -= cost
        action()
        if self.state == "shop":
            self.shop_sel = min(self.shop_sel, len(self.shop_items()) - 1)

    # --------------------------------------------------------------- update

    def update(self, dt, keys):
        self.time += dt
        if self.state != "play" or self.paused:
            return
        p, lv = self.player, self.level
        self.banner = max(0, self.banner - dt)

        # --- player movement
        direction = (1 if keys[pygame.K_RIGHT] else 0) - (1 if keys[pygame.K_LEFT] else 0)
        p.moving = direction != 0
        if direction:
            p.facing = direction
        if keys[pygame.K_UP] and p.on_ground:
            p.vy = -JUMP
        p.vy += GRAVITY * dt
        p.move(direction * SPEED * dt, p.vy * dt, lv.solids)
        p.cooldown = max(0, p.cooldown - dt)
        p.swing = max(0, p.swing - dt)

        r = p.rect

        # --- one touch of lava, flame or ghost ends the run
        if lv.pool and r.bottom > FLOOR_Y + LAVA_DEPTH:
            return self.die("You fell in the lava.")
        if lv.flame_x is not None:
            lv.flame_t += dt
            if lv.flame_phase == "on" and r.colliderect(lv.flame_rect.inflate(-8, 0)):
                return self.die("A flamethrower roasted you.")

        # --- attacking
        if keys[pygame.K_SPACE] and p.cooldown <= 0:
            if p.weapon == "sword":
                p.swing = SWING_TIME
                p.swing_hits = []
                p.cooldown = SWING_COOLDOWN
            else:
                gun = GUNS[p.weapon]
                p.cooldown = gun["cooldown"]
                self.lasers.append(dict(x=r.centerx + p.facing * 20, y=r.y + 24, dir=p.facing,
                                        dmg=gun["dmg"], color=gun["color"]))

        if p.swing > 0 and p.weapon == "sword":
            limit = 2 if p.double else 1
            box = p.sword_box()
            targets = sorted((g for g in lv.ghosts if g not in p.swing_hits and box.colliderect(g.rect)),
                             key=lambda g: abs(g.x - r.centerx))
            for g in targets[:limit - len(p.swing_hits)]:
                p.swing_hits.append(g)
                self.hit_ghost(g, SWORD_DMG[p.dmg_lvl], p.facing)

        for shot in self.lasers[:]:
            shot["x"] += shot["dir"] * 760 * dt
            box = pygame.Rect(shot["x"] - 11, shot["y"] - 3, 22, 6)
            hit = next((g for g in lv.ghosts if box.colliderect(g.rect)), None)
            if hit:
                self.hit_ghost(hit, shot["dmg"], shot["dir"])
            if hit or not -30 < shot["x"] < W + 30:
                self.lasers.remove(shot)

        # --- ghosts
        for g in lv.ghosts:
            g.flash = max(0, g.flash - dt)
            if g.spawn > 0:
                g.spawn -= dt
                continue
            tx, ty = r.centerx, r.centery + math.sin(self.time * 2.5 + g.phase) * 20
            dx, dy = tx - g.x, ty - g.y
            dist = math.hypot(dx, dy) or 1
            g.x += (dx / dist * g.speed + g.kb) * dt
            g.y += dy / dist * g.speed * dt
            g.kb *= max(0, 1 - 5 * dt)
            for other in lv.ghosts:      # keep ghosts from stacking perfectly
                if other is not g and abs(other.x - g.x) < 30 and abs(other.y - g.y) < 30:
                    g.x += (30 if g.x >= other.x else -30) * dt
            g.x = max(18, min(W - 18, g.x))
            g.y = max(CEIL_Y + 24, min(FLOOR_Y - 14, g.y))
            if g.rect.inflate(-10, -10).colliderect(r):
                return self.die("A ghost got you.")

        # --- effects
        for part in self.particles[:]:
            part[0] += part[2] * dt
            part[1] += part[3] * dt
            part[3] += 500 * dt
            part[4] -= dt
            if part[4] <= 0:
                self.particles.remove(part)
        for pop in self.popups[:]:
            pop[1] -= 40 * dt
            pop[3] -= dt
            if pop[3] <= 0:
                self.popups.remove(pop)

        # --- outcome
        if not lv.ghosts and r.colliderect(lv.door.inflate(-20, 0)):
            self.score += STORY_POINTS
            if self.story >= TOP_STORY:
                self.state = "win"
                self.save_score()
            else:
                self.state = "shop"

    def hit_ghost(self, g, dmg, direction):
        g.hp -= dmg
        g.flash = 0.12
        g.kb = 240 * direction
        self.burst(g.x, g.y, (210, 230, 255), 6)
        if g.hp <= 0:
            self.level.ghosts.remove(g)
            reward = 8 + self.story
            self.coins += reward
            self.score += GHOST_POINTS
            self.burst(g.x, g.y, (210, 230, 255), 22)
            self.popups.append([g.x, g.y - 20, f"+{reward}", 0.9])

    def burst(self, x, y, color, n):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            v = random.uniform(40, 220)
            self.particles.append([x, y, math.cos(a) * v, math.sin(a) * v - 80,
                                   random.uniform(0.3, 0.7), color])

    # ----------------------------------------------------------------- draw

    def text(self, msg, size, color, pos, anchor="topleft"):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.Font(None, size)
        img = self.fonts[size].render(msg, True, color)
        rect = img.get_rect(**{anchor: pos})
        self.screen.blit(img, rect)
        return rect

    def dim(self, alpha=170):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((8, 6, 16, alpha))
        self.screen.blit(veil, (0, 0))

    def draw(self):
        if self.state == "title":
            self.draw_title()
            return
        self.draw_world()
        self.draw_hud()
        if self.state == "shop":
            self.draw_shop()
        elif self.state == "dead":
            self.draw_game_over("YOU DIED", (255, 90, 80), f"{self.cause}  You reached story {self.story}.")
        elif self.state == "win":
            self.draw_game_over("YOU ESCAPED THE TOWER!", (255, 220, 90), f"All {TOP_STORY} stories cleared.")
        elif self.paused:
            self.dim(140)
            self.text("PAUSED", 72, (240, 240, 250), (W // 2, 250), "center")
            self.text("Press P to keep climbing", 26, (190, 190, 210), (W // 2, 310), "center")

    def draw_game_over(self, title, color, detail):
        self.dim()
        self.text(title, 72, color, (W // 2, 130), "center")
        self.text(detail, 30, (230, 230, 240), (W // 2, 188), "center")
        self.text(f"Score: {self.score}", 48, (255, 255, 255), (W // 2, 240), "center")
        if self.new_best:
            self.text("NEW HIGH SCORE!", 30, (120, 255, 150), (W // 2, 278), "center")
        self.text("Saved high scores", 24, (170, 170, 190), (W // 2, 318), "center")
        marked = False
        for i, (score, story) in enumerate(self.scores):
            mine = not marked and (score, story) == (self.score, self.story)
            marked = marked or mine
            self.text(f"{i + 1}.   {score} points   (story {story})", 26,
                      (255, 225, 110) if mine else (200, 200, 220), (W // 2, 346 + i * 26), "center")
        self.text("Enter: redo the game        Esc: quit", 32, (255, 255, 255), (W // 2, 474), "center")

    def draw_title(self):
        scr = self.screen
        scr.blit(self.backdrop, (0, 0))
        self.dim(120)
        self.text("THE TOWER", 120, (255, 220, 90), (W // 2, 130), "center")
        self.text(f"Climb {TOP_STORY} stories of ghosts, lava and flamethrowers to escape.", 30,
                  (225, 225, 240), (W // 2, 215), "center")
        lines = [
            ("Left / Right", "move"),
            ("Up", "jump (hop across lava on the rocks)"),
            ("Space", "swing your sword or fire your laser gun"),
            ("Q", "swap weapons once you own a laser gun"),
            ("P", "pause"),
        ]
        for i, (k, what) in enumerate(lines):
            y = 280 + i * 34
            self.text(k, 28, (140, 220, 255), (W // 2 - 20, y), "topright")
            self.text(what, 28, (225, 225, 240), (W // 2 + 4, y))
        self.text("Defeat every ghost on a story to unlock the stairs.", 26, (190, 190, 210), (W // 2, 478), "center")
        self.text("One touch from a ghost, lava or a flame and the run is over.", 26, (255, 150, 140), (W // 2, 506), "center")
        if self.scores:
            self.text(f"High score: {self.scores[0][0]}", 26, (255, 225, 110), (W // 2, 248), "center")
        if int(self.time * 2) % 2 == 0:
            self.text("Press Enter to start", 38, (255, 255, 255), (W // 2, 556), "center")

    def draw_world(self):
        scr, lv, p = self.screen, self.level, self.player
        scr.blit(self.backdrop, (0, 0))

        for tx in (200, 560):       # wall torches
            pygame.draw.rect(scr, (90, 70, 50), (tx - 3, 250, 6, 26))
            flick = math.sin(self.time * 12 + tx) * 2
            pygame.draw.circle(scr, (255, 150, 40), (tx, 244), 9 + flick)
            pygame.draw.circle(scr, (255, 230, 120), (tx, 246), 5)

        # lava pool with stepping-stone rocks
        if lv.pool:
            pygame.draw.rect(scr, (18, 12, 16), lv.pool)
            top = FLOOR_Y + LAVA_DEPTH
            wave = [(lv.pool.left, H)]
            for x in range(lv.pool.left, lv.pool.right + 1, 8):
                wave.append((x, top + math.sin(x * 0.06 + self.time * 3) * 3))
            wave.append((lv.pool.right, H))
            pygame.draw.polygon(scr, (240, 90, 20), wave)
            pygame.draw.lines(scr, (255, 210, 80), False, wave[1:-1], 3)
            for i in range(5):
                bx = lv.pool.left + 20 + (i * 97 + int(self.time * 30)) % (lv.pool.w - 40)
                by = top + 16 + (i * 23) % 50
                pygame.draw.circle(scr, (255, 170, 50), (bx, by), 3 + i % 3)
            for rock in lv.rocks:
                pts = [(rock.left - 3, H), (rock.left + 2, rock.top + 6), (rock.left + 8, rock.top),
                       (rock.right - 8, rock.top), (rock.right - 2, rock.top + 6), (rock.right + 3, H)]
                pygame.draw.polygon(scr, (112, 108, 118), pts)
                pygame.draw.line(scr, (170, 166, 178), (rock.left + 8, rock.top + 1), (rock.right - 8, rock.top + 1), 3)

        for f in lv.floors:
            pygame.draw.rect(scr, (74, 68, 90), f)
            pygame.draw.rect(scr, (112, 104, 132), (f.x, f.y, f.w, 6))

        # door / stairs up
        d = lv.door
        opened = not lv.ghosts
        pygame.draw.rect(scr, (96, 88, 112), d.inflate(12, 6).move(0, -3), border_radius=8)
        if opened:
            pygame.draw.rect(scr, (14, 12, 20), d)
            for i in range(4):
                pygame.draw.rect(scr, (120, 220, 140), (d.x + 6 + i * 9, d.bottom - 12 - i * 14, 46 - 6 - i * 9, 5))
            bob = math.sin(self.time * 5) * 4
            pygame.draw.polygon(scr, (120, 255, 150), [(d.centerx, d.top - 34 + bob), (d.centerx - 12, d.top - 18 + bob),
                                                       (d.centerx + 12, d.top - 18 + bob)])
        else:
            pygame.draw.rect(scr, (92, 58, 36), d)
            pygame.draw.line(scr, (60, 38, 24), (d.centerx, d.top), (d.centerx, d.bottom), 2)
            pygame.draw.rect(scr, (200, 60, 60), (d.centerx - 7, d.centery - 4, 14, 12), border_radius=2)
            pygame.draw.arc(scr, (200, 60, 60), (d.centerx - 6, d.centery - 13, 12, 16), 0, math.pi, 3)

        # flamethrower
        if lv.flame_x is not None:
            fx = lv.flame_x
            phase = lv.flame_phase
            if phase == "on":
                fr = lv.flame_rect
                for _ in range(46):
                    k = random.random()
                    y = fr.top + k * fr.h
                    x = fx + random.uniform(-1, 1) * (8 + 14 * k)
                    color = random.choice(((255, 90, 20), (255, 150, 30), (255, 220, 90)))
                    pygame.draw.circle(scr, color, (x, y), random.uniform(6, 15))
            pygame.draw.rect(scr, (70, 72, 82), (fx - 5, CEIL_Y, 10, 18))
            pygame.draw.polygon(scr, (130, 134, 148), [(fx - 9, CEIL_Y + 16), (fx + 9, CEIL_Y + 16),
                                                       (fx + 15, CEIL_Y + 36), (fx - 15, CEIL_Y + 36)])
            if phase == "warn" and int(self.time * 16) % 2:
                pygame.draw.circle(scr, (255, 200, 70), (fx, CEIL_Y + 40), 7)

        for g in lv.ghosts:
            self.draw_ghost(g)
        self.draw_player()

        for shot in self.lasers:
            pygame.draw.rect(scr, shot["color"], (shot["x"] - 11, shot["y"] - 2, 22, 5), border_radius=2)
            pygame.draw.rect(scr, (255, 255, 255), (shot["x"] - 7, shot["y"] - 1, 14, 2))
        for x, y, _, _, life, color in self.particles:
            pygame.draw.circle(scr, color, (x, y), max(1, life * 6))
        for x, y, msg, _ in self.popups:
            self.text(msg, 28, (255, 220, 90), (x, y), "center")

        if self.story == 1 and lv.ghosts:
            self.text("Arrow keys: move and jump     Space: attack", 24, (200, 200, 220), (W // 2, 110), "center")
            self.text("Defeat every ghost to unlock the stairs", 24, (200, 200, 220), (W // 2, 136), "center")
        if self.banner > 0 and self.state == "play":
            img = self.fonts[96].render(f"STORY {self.story}", True, (255, 255, 255))
            img.set_alpha(int(255 * min(1, self.banner)))
            scr.blit(img, img.get_rect(center=(W // 2, 220)))

    def draw_ghost(self, g):
        s = pygame.Surface((44, 54), pygame.SRCALPHA)
        body = (255, 255, 255) if g.flash > 0 else (196, 222, 255)
        pygame.draw.circle(s, body, (22, 20), 18)
        pygame.draw.rect(s, body, (4, 20, 36, 22))
        for i in range(3):
            pygame.draw.circle(s, body, (10 + 12 * i, 42 + math.sin(self.time * 8 + i * 2 + g.phase) * 2), 6)
        look = 3 if self.player.rect.centerx > g.x else -3
        for ex in (15, 29):
            pygame.draw.circle(s, (26, 26, 60), (ex + look, 19), 4)
        pygame.draw.ellipse(s, (26, 26, 60), (17 + look, 27, 10, 7))
        if g.spawn > 0:
            s.set_alpha(int(200 * (1 - g.spawn / 1.2)))
        else:
            s.set_alpha(220)
        self.screen.blit(s, (g.x - 22, g.y - 24))
        if g.hp < g.max_hp:
            pygame.draw.rect(self.screen, (40, 30, 50), (g.x - 18, g.y - 34, 36, 5))
            pygame.draw.rect(self.screen, (120, 230, 140), (g.x - 18, g.y - 34, 36 * g.hp / g.max_hp, 5))

    def draw_player(self):
        scr, p = self.screen, self.player
        if self.state == "dead":
            return
        r, f = p.rect, p.facing
        step = math.sin(self.time * 16) * 5 if p.moving and p.on_ground else 0
        pygame.draw.rect(scr, (44, 52, 96), (r.centerx - 9 + step, r.bottom - 12, 7, 12))
        pygame.draw.rect(scr, (44, 52, 96), (r.centerx + 2 - step, r.bottom - 12, 7, 12))
        pygame.draw.rect(scr, (60, 140, 230), (r.x + 3, r.y + 16, PW - 6, 18), border_radius=4)
        pygame.draw.circle(scr, (242, 206, 170), (r.centerx, r.y + 9), 9)
        pygame.draw.circle(scr, (30, 30, 40), (r.centerx + f * 4, r.y + 8), 2)
        hand = (r.centerx + f * 10, r.y + 26)
        pygame.draw.circle(scr, (242, 206, 170), hand, 4)

        if p.weapon == "sword":
            if p.swing > 0:
                angle = math.radians(-80 + 120 * (1 - p.swing / SWING_TIME))
            else:
                angle = math.radians(-62)
            tip = (hand[0] + f * math.cos(angle) * p.blade, hand[1] + math.sin(angle) * p.blade)
            steel = [(210, 214, 226), (190, 230, 255), (140, 255, 200), (255, 230, 120),
                     (255, 160, 90), (255, 110, 200)][p.dmg_lvl]
            pygame.draw.line(scr, steel, hand, tip, 4 + p.dmg_lvl // 2)
            guard = (hand[0] + f * math.cos(angle) * 6, hand[1] + math.sin(angle) * 6)
            nx, ny = -math.sin(angle) * 6, f * math.cos(angle) * 6
            pygame.draw.line(scr, (150, 110, 60), (guard[0] - nx, guard[1] - ny), (guard[0] + nx, guard[1] + ny), 3)
            if p.swing > 0:
                box = p.sword_box()
                arc = pygame.Surface(box.size, pygame.SRCALPHA)
                pygame.draw.ellipse(arc, (255, 255, 255, 50), arc.get_rect().inflate(box.w, 0).move(-f * box.w // 2, 0))
                scr.blit(arc, box)
        else:
            color = GUNS[p.weapon]["color"]
            length = 18 if p.weapon == "pistol" else 28
            x = hand[0] if f > 0 else hand[0] - length
            pygame.draw.rect(scr, (60, 62, 74), (x, hand[1] - 4, length, 7), border_radius=2)
            pygame.draw.rect(scr, color, (x + (length - 5 if f > 0 else 0), hand[1] - 4, 5, 7))

    def draw_hud(self):
        scr, p = self.screen, self.player
        pygame.draw.rect(scr, (40, 36, 54), (0, 0, W, CEIL_Y))
        pygame.draw.rect(scr, (96, 88, 112), (0, CEIL_Y - 5, W, 5))
        self.text(f"STORY {self.story}", 44, (255, 255, 255), (18, 10))
        self.text(f"of {TOP_STORY}", 22, (170, 170, 190), (20, 44))

        self.text("SCORE", 20, (170, 170, 190), (210, 12))
        self.text(str(self.score), 34, (255, 255, 255), (210, 28))

        pygame.draw.circle(scr, (255, 210, 70), (400, 32), 11)
        pygame.draw.circle(scr, (200, 150, 30), (400, 32), 11, 2)
        self.text(str(self.coins), 34, (255, 225, 110), (418, 21))

        if p.weapon == "sword":
            extra = ", double strike" if p.double else ""
            self.text("Sword", 30, (255, 255, 255), (530, 10))
            self.text(f"size {p.len_lvl + 1}, damage {SWORD_DMG[p.dmg_lvl]}{extra}", 20, (170, 170, 190), (530, 36))
        else:
            gun = GUNS[p.weapon]
            self.text(gun["name"], 30, gun["color"], (530, 10))
            pygame.draw.rect(scr, (70, 64, 88), (530, 40, 120, 8), border_radius=3)
            ready = 1 - p.cooldown / gun["cooldown"]
            pygame.draw.rect(scr, gun["color"] if ready >= 1 else (150, 150, 160), (530, 40, 120 * ready, 8), border_radius=3)
        if p.guns:
            self.text("Q: swap weapon", 20, (170, 170, 190), (W - 18, 42), "topright")

        left = len(self.level.ghosts)
        msg = f"Ghosts left: {left}" if left else "Stairs unlocked!"
        self.text(msg, 28, (196, 222, 255) if left else (120, 255, 150), (W - 18, 14), "topright")

    def draw_shop(self):
        scr = self.screen
        self.dim()
        panel = pygame.Rect(150, 86, 660, 470)
        pygame.draw.rect(scr, (44, 40, 62), panel, border_radius=12)
        pygame.draw.rect(scr, (255, 210, 70), panel, 3, border_radius=12)
        self.text(f"STORY {self.story} CLEARED  -  SHOP", 40, (255, 220, 90), (panel.centerx, panel.top + 34), "center")
        self.text(f"Coins: {self.coins}", 28, (255, 225, 110), (panel.right - 24, panel.top + 66), "topright")
        self.text("Up/Down: choose    Enter: buy", 22, (170, 170, 190), (panel.left + 24, panel.top + 70))

        items = self.shop_items()
        for i, (label, status, cost, action, _) in enumerate(items):
            row = pygame.Rect(panel.left + 20, panel.top + 104 + i * 36, panel.w - 40, 32)
            if i == self.shop_sel:
                pygame.draw.rect(scr, (78, 70, 112), row, border_radius=6)
                pygame.draw.rect(scr, (140, 220, 255), row, 2, border_radius=6)
            usable = action is not None
            self.text(label, 28, (255, 255, 255) if usable else (130, 126, 150), (row.left + 12, row.top + 6))
            self.text(status, 22, (170, 200, 230) if usable else (130, 126, 150), (row.left + 250, row.top + 9))
            if cost is not None:
                afford = cost <= self.coins
                self.text(f"{cost} coins", 26, (255, 225, 110) if afford else (220, 100, 100),
                          (row.right - 12, row.top + 7), "topright")
        desc = items[self.shop_sel][4]
        self.text(desc, 24, (225, 225, 240), (panel.centerx, panel.bottom - 54), "center")
        if self.shop_msg:
            self.text(self.shop_msg, 26, (255, 110, 100), (panel.centerx, panel.bottom - 26), "center")


async def main():
    pygame.init()
    pygame.display.set_caption("The Tower")
    screen = pygame.display.set_mode((W, H), 0 if WEB else pygame.SCALED)
    clock = pygame.time.Clock()
    game = Game(screen)
    while True:
        dt = min(clock.tick(FPS) / 1000, 1 / 30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                game.on_key(event.key)
        game.update(dt, pygame.key.get_pressed())
        game.draw()
        pygame.display.flip()
        await asyncio.sleep(0)      # hands control back to the browser each frame


if __name__ == "__main__":
    asyncio.run(main())
