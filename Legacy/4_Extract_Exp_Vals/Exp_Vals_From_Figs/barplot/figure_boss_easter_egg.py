from __future__ import annotations

import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    PYSIDE6_AVAILABLE = True
    PYSIDE6_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on local GUI environment
    QtCore = None
    QtGui = None
    QtWidgets = None
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(exc)


if PYSIDE6_AVAILABLE:

    @dataclass
    class WeaponConfig:
        name: str
        magazine_size: int
        reserve_start: int
        damage: float
        bullet_speed: float
        cooldown: float
        reload_time: float
        pellets: int = 1
        spread_degrees: float = 0.0
        projectile_radius: float = 4.0
        is_grenade: bool = False


    @dataclass
    class Weapon:
        config: WeaponConfig
        magazine: int = 0
        reserve: int = 0
        unlocked: bool = True
        last_fire_time: float = 0.0
        reloading_until: float = 0.0

        def __post_init__(self):
            self.magazine = self.config.magazine_size
            self.reserve = self.config.reserve_start

        def can_fire(self, now: float) -> bool:
            return self.unlocked and self.magazine > 0 and now >= self.reloading_until and now - self.last_fire_time >= self.config.cooldown

        def reload(self, now: float) -> bool:
            if not self.unlocked or self.reserve <= 0 or self.magazine >= self.config.magazine_size or now < self.reloading_until:
                return False
            self.reloading_until = now + self.config.reload_time
            return True

        def finish_reload_if_ready(self, now: float) -> None:
            if self.reloading_until and now >= self.reloading_until:
                needed = self.config.magazine_size - self.magazine
                loaded = min(needed, self.reserve)
                self.magazine += loaded
                self.reserve -= loaded
                self.reloading_until = 0.0


    @dataclass
    class Player:
        x: float = 500.0
        y: float = 610.0
        radius: float = 16.0
        hp: float = 100.0
        speed: float = 330.0


    @dataclass
    class Boss:
        x: float = 360.0
        y: float = 55.0
        w: float = 280.0
        h: float = 160.0
        hp: float = 1000.0
        max_hp: float = 1000.0
        vx: float = 120.0
        phase: int = 1
        next_attack_time: float = 0.0
        next_dash_time: float = 0.0

        def rect(self) -> QtCore.QRectF:
            return QtCore.QRectF(self.x, self.y, self.w, self.h)

        def center(self) -> QtCore.QPointF:
            return QtCore.QPointF(self.x + self.w / 2.0, self.y + self.h / 2.0)


    @dataclass
    class Bullet:
        x: float
        y: float
        vx: float
        vy: float
        damage: float
        radius: float
        kind: str = "bullet"
        born: float = field(default_factory=time.monotonic)
        fuse_time: float = 1.0


    @dataclass
    class EnemyProjectile:
        x: float
        y: float
        vx: float
        vy: float
        damage: float
        radius: float
        homing: bool = False
        born: float = field(default_factory=time.monotonic)


    @dataclass
    class ItemPickup:
        x: float
        y: float
        kind: str
        radius: float = 14.0


    @dataclass
    class AxisLaser:
        orientation: str
        pos: float
        warning_until: float
        expire_at: float
        damage_done: bool = False


    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))


    def distance(x1: float, y1: float, x2: float, y2: float) -> float:
        return math.hypot(x2 - x1, y2 - y1)


    def unit_vector(dx: float, dy: float) -> tuple[float, float]:
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return 0.0, -1.0
        return dx / length, dy / length


    def crop_non_background_regions(pixmap: QtGui.QPixmap | None, target_size: int = 30) -> QtGui.QPixmap | None:
        if pixmap is None or pixmap.isNull():
            return None
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_RGB32)
        w, h = image.width(), image.height()
        if w <= 0 or h <= 0:
            return None
        min_x, min_y, max_x, max_y = w, h, -1, -1
        step = max(1, int(max(w, h) / 350))
        for y in range(0, h, step):
            for x in range(0, w, step):
                color = QtGui.QColor(image.pixel(x, y))
                # Most figures have near-white backgrounds.
                if not (color.red() > 238 and color.green() > 238 and color.blue() > 238):
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)
        if max_x <= min_x or max_y <= min_y:
            return None
        crop_rect = QtCore.QRect(min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y))
        return QtGui.QPixmap.fromImage(image.copy(crop_rect)).scaled(
            target_size,
            target_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )


    class GameCanvas(QtWidgets.QWidget):
        def __init__(self, figure_pixmap: QtGui.QPixmap | None = None, parent=None):
            super().__init__(parent)
            self.setMinimumSize(1000, 700)
            self.setMouseTracking(True)
            self.setFocusPolicy(QtCore.Qt.StrongFocus)
            self.figure_pixmap = figure_pixmap if figure_pixmap is not None and not figure_pixmap.isNull() else None
            self.projectile_pixmap = crop_non_background_regions(self.figure_pixmap)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(16)
            self.keys: set[int] = set()
            self.mouse_pos = QtCore.QPointF(500, 500)
            self.rng = random.Random()
            self.reset_game()

        def reset_game(self) -> None:
            self.player = Player(x=self.width() / 2.0, y=max(520.0, self.height() - 90.0))
            self.boss = Boss(x=self.width() / 2.0 - 150.0)
            self.weapon_order = ["rifle", "pistol", "shotgun", "grenade"]
            configs = {
                "rifle": WeaponConfig("rifle", 30, 90, 16, 880, 0.09, 1.2, projectile_radius=3),
                "pistol": WeaponConfig("pistol", 8, 40, 24, 720, 0.32, 0.8, projectile_radius=4),
                "shotgun": WeaponConfig("shotgun", 5, 10, 14, 680, 0.8, 1.15, pellets=7, spread_degrees=26, projectile_radius=3),
                "grenade": WeaponConfig("grenade", 1, 3, 95, 430, 0.75, 1.0, projectile_radius=8, is_grenade=True),
            }
            self.weapons = {name: Weapon(config) for name, config in configs.items()}
            self.weapons["shotgun"].unlocked = False
            self.weapons["grenade"].unlocked = False
            self.current_weapon_index = 0
            self.bullets: list[Bullet] = []
            self.enemy_projectiles: list[EnemyProjectile] = []
            self.items: list[ItemPickup] = []
            self.lasers: list[AxisLaser] = []
            self.explosions: list[tuple[float, float, float, float]] = []
            now = time.monotonic()
            self.last_time = now
            self.next_item_time = now + 2.0
            self.boss.next_attack_time = now + 1.2
            self.boss.next_dash_time = now + 3.0
            self.game_over = False
            self.victory = False
            self.message = ""

        def current_weapon(self) -> Weapon:
            for _ in range(len(self.weapon_order)):
                name = self.weapon_order[self.current_weapon_index]
                weapon = self.weapons[name]
                if weapon.unlocked:
                    return weapon
                self.current_weapon_index = (self.current_weapon_index + 1) % len(self.weapon_order)
            return self.weapons["rifle"]

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Escape:
                self.window().close()
                return
            if event.key() == QtCore.Qt.Key_R and not event.isAutoRepeat():
                self.current_weapon().reload(time.monotonic())
            elif event.key() == QtCore.Qt.Key_Q and not event.isAutoRepeat():
                self.switch_weapon(-1)
            elif event.key() == QtCore.Qt.Key_E and not event.isAutoRepeat():
                self.switch_weapon(1)
            elif event.key() in (QtCore.Qt.Key_1, QtCore.Qt.Key_2, QtCore.Qt.Key_3, QtCore.Qt.Key_4):
                self.select_weapon_by_number(event.key() - QtCore.Qt.Key_1)
            elif event.key() == QtCore.Qt.Key_Space:
                self.fire()
            else:
                self.keys.add(event.key())

        def keyReleaseEvent(self, event):
            self.keys.discard(event.key())

        def mouseMoveEvent(self, event):
            self.mouse_pos = event.position()

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.LeftButton:
                self.fire()

        def switch_weapon(self, direction: int) -> None:
            for _ in range(len(self.weapon_order)):
                self.current_weapon_index = (self.current_weapon_index + direction) % len(self.weapon_order)
                if self.weapons[self.weapon_order[self.current_weapon_index]].unlocked:
                    return

        def select_weapon_by_number(self, idx: int) -> None:
            if 0 <= idx < len(self.weapon_order) and self.weapons[self.weapon_order[idx]].unlocked:
                self.current_weapon_index = idx

        def fire(self) -> None:
            if self.game_over or self.victory:
                self.reset_game()
                return
            now = time.monotonic()
            weapon = self.current_weapon()
            weapon.finish_reload_if_ready(now)
            if not weapon.can_fire(now):
                return
            weapon.magazine -= 1
            weapon.last_fire_time = now
            cfg = weapon.config
            ux, uy = unit_vector(self.mouse_pos.x() - self.player.x, self.mouse_pos.y() - self.player.y)
            base_angle = math.atan2(uy, ux)
            pellet_count = max(1, cfg.pellets)
            for i in range(pellet_count):
                offset = 0.0
                if pellet_count > 1:
                    spread = math.radians(cfg.spread_degrees)
                    offset = -spread / 2.0 + spread * (i / max(1, pellet_count - 1))
                angle = base_angle + offset + self.rng.uniform(-0.025, 0.025)
                self.bullets.append(
                    Bullet(
                        self.player.x,
                        self.player.y,
                        math.cos(angle) * cfg.bullet_speed,
                        math.sin(angle) * cfg.bullet_speed,
                        cfg.damage,
                        cfg.projectile_radius,
                        kind=cfg.name,
                        fuse_time=0.9 if cfg.is_grenade else 99,
                    )
                )

        def tick(self) -> None:
            now = time.monotonic()
            dt = min(0.04, now - self.last_time)
            self.last_time = now
            for weapon in self.weapons.values():
                weapon.finish_reload_if_ready(now)
            if not self.game_over and not self.victory:
                self.update_player(dt)
                self.update_boss(dt, now)
                self.update_bullets(dt, now)
                self.update_enemy_projectiles(dt)
                self.update_lasers(now)
                self.update_items(now)
                self.check_end_conditions()
            self.update()

        def update_player(self, dt: float) -> None:
            dx = (QtCore.Qt.Key_D in self.keys) - (QtCore.Qt.Key_A in self.keys)
            dy = (QtCore.Qt.Key_S in self.keys) - (QtCore.Qt.Key_W in self.keys)
            if dx or dy:
                ux, uy = unit_vector(dx, dy)
                self.player.x += ux * self.player.speed * dt
                self.player.y += uy * self.player.speed * dt
            self.player.x = clamp(self.player.x, self.player.radius, self.width() - self.player.radius)
            self.player.y = clamp(self.player.y, self.height() * 0.43, self.height() - self.player.radius)

        def update_boss(self, dt: float, now: float) -> None:
            self.boss.phase = 2 if self.boss.hp <= self.boss.max_hp * 0.5 else 1
            speed_mult = 1.25 if self.boss.phase == 2 else 1.0
            self.boss.x += self.boss.vx * speed_mult * dt
            if self.boss.x < 80 or self.boss.x + self.boss.w > self.width() - 80:
                self.boss.vx *= -1
            target_y = 65 + 35 * math.sin(now * 1.4)
            self.boss.y += (target_y - self.boss.y) * min(1.0, dt * 2.2)
            self.boss.y = clamp(self.boss.y, 35, self.height() * 0.28)
            if now >= self.boss.next_dash_time:
                self.boss.vx = self.rng.choice([-1, 1]) * self.rng.uniform(150, 260)
                self.boss.next_dash_time = now + self.rng.uniform(2.0, 4.0)
            if now >= self.boss.next_attack_time:
                self.boss_attack(now)
                interval = self.rng.uniform(0.85, 1.45) * (0.72 if self.boss.phase == 2 else 1.0)
                self.boss.next_attack_time = now + interval

        def boss_attack(self, now: float) -> None:
            patterns = ["single", "spread", "bar_rain", "axis_laser", "homing"]
            weights = [3, 2, 2, 1, 1] if self.boss.phase == 1 else [2, 4, 2, 3, 2]
            pattern = self.rng.choices(patterns, weights=weights, k=1)[0]
            center = self.boss.center()
            if pattern == "single":
                self.spawn_enemy_projectile(center.x(), center.y(), self.player.x, self.player.y, 300, 10)
            elif pattern == "spread":
                base = math.atan2(self.player.y - center.y(), self.player.x - center.x())
                for offset in [-0.55, -0.27, 0, 0.27, 0.55]:
                    angle = base + offset
                    self.enemy_projectiles.append(EnemyProjectile(center.x(), center.y(), math.cos(angle) * 250, math.sin(angle) * 250, 8, 8))
            elif pattern == "bar_rain":
                for _ in range(9 if self.boss.phase == 2 else 6):
                    x = self.rng.uniform(40, self.width() - 40)
                    self.enemy_projectiles.append(EnemyProjectile(x, -20, 0, self.rng.uniform(210, 330), 9, 9))
            elif pattern == "axis_laser":
                if self.rng.random() < 0.5:
                    pos = clamp(self.player.x + self.rng.uniform(-80, 80), 50, self.width() - 50)
                    self.lasers.append(AxisLaser("vertical", pos, now + 0.65, now + 0.95))
                else:
                    pos = clamp(self.player.y + self.rng.uniform(-60, 60), self.height() * 0.35, self.height() - 40)
                    self.lasers.append(AxisLaser("horizontal", pos, now + 0.65, now + 0.95))
            elif pattern == "homing":
                self.spawn_enemy_projectile(center.x(), center.y(), self.player.x, self.player.y, 145, 12, homing=True)

        def spawn_enemy_projectile(self, x, y, target_x, target_y, speed, damage, homing=False):
            ux, uy = unit_vector(target_x - x, target_y - y)
            self.enemy_projectiles.append(EnemyProjectile(x, y, ux * speed, uy * speed, damage, 8, homing=homing))

        def update_bullets(self, dt: float, now: float) -> None:
            boss_rect = self.boss.rect()
            kept = []
            for bullet in self.bullets:
                bullet.x += bullet.vx * dt
                bullet.y += bullet.vy * dt
                if bullet.kind == "grenade" and now - bullet.born >= bullet.fuse_time:
                    self.explode_grenade(bullet.x, bullet.y, now)
                    continue
                if boss_rect.adjusted(-8, -8, 8, 8).contains(bullet.x, bullet.y):
                    self.boss.hp = max(0, self.boss.hp - bullet.damage)
                    if bullet.kind == "grenade":
                        self.explode_grenade(bullet.x, bullet.y, now)
                    continue
                if -80 <= bullet.x <= self.width() + 80 and -80 <= bullet.y <= self.height() + 80:
                    kept.append(bullet)
            self.bullets = kept
            self.explosions = [e for e in self.explosions if e[3] > now]

        def explode_grenade(self, x: float, y: float, now: float) -> None:
            radius = 95.0
            self.explosions.append((x, y, radius, now + 0.25))
            c = self.boss.center()
            d = distance(x, y, c.x(), c.y())
            if d < radius + max(self.boss.w, self.boss.h) * 0.25:
                self.boss.hp = max(0, self.boss.hp - 130 * max(0.25, 1.0 - d / (radius * 1.8)))

        def update_enemy_projectiles(self, dt: float) -> None:
            kept = []
            for p in self.enemy_projectiles:
                if p.homing:
                    ux, uy = unit_vector(self.player.x - p.x, self.player.y - p.y)
                    p.vx = p.vx * 0.94 + ux * 19
                    p.vy = p.vy * 0.94 + uy * 19
                p.x += p.vx * dt
                p.y += p.vy * dt
                if distance(p.x, p.y, self.player.x, self.player.y) <= p.radius + self.player.radius:
                    self.player.hp = max(0, self.player.hp - p.damage)
                    continue
                if -80 <= p.x <= self.width() + 80 and -80 <= p.y <= self.height() + 80:
                    kept.append(p)
            self.enemy_projectiles = kept

        def update_lasers(self, now: float) -> None:
            for laser in self.lasers:
                if now >= laser.warning_until and not laser.damage_done:
                    if laser.orientation == "vertical" and abs(self.player.x - laser.pos) < 22:
                        self.player.hp = max(0, self.player.hp - 22)
                    if laser.orientation == "horizontal" and abs(self.player.y - laser.pos) < 22:
                        self.player.hp = max(0, self.player.hp - 22)
                    laser.damage_done = True
            self.lasers = [laser for laser in self.lasers if now < laser.expire_at]

        def update_items(self, now: float) -> None:
            if now >= self.next_item_time and len(self.items) < 7:
                kind = self.rng.choice(["rifle_ammo", "pistol_ammo", "shotgun", "grenade", "health"])
                self.items.append(ItemPickup(self.rng.uniform(50, self.width() - 50), self.rng.uniform(self.height() * 0.45, self.height() - 55), kind))
                self.next_item_time = now + self.rng.uniform(2.2, 4.0)
            kept = []
            for item in self.items:
                if distance(item.x, item.y, self.player.x, self.player.y) <= item.radius + self.player.radius:
                    self.apply_item(item)
                else:
                    kept.append(item)
            self.items = kept

        def apply_item(self, item: ItemPickup) -> None:
            if item.kind == "health":
                self.player.hp = min(100, self.player.hp + 28)
            elif item.kind == "rifle_ammo":
                self.weapons["rifle"].reserve += 30
            elif item.kind == "pistol_ammo":
                self.weapons["pistol"].reserve += 16
            elif item.kind == "shotgun":
                self.weapons["shotgun"].unlocked = True
                self.weapons["shotgun"].reserve += 8
            elif item.kind == "grenade":
                self.weapons["grenade"].unlocked = True
                self.weapons["grenade"].reserve += 2

        def check_end_conditions(self) -> None:
            if self.boss.hp <= 0:
                self.victory = True
                self.message = "Figure defeated. Manual extraction still required. Click or Space to restart."
            elif self.player.hp <= 0:
                self.game_over = True
                self.message = "Game Over. Click or Space to restart."

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.fillRect(self.rect(), QtGui.QColor(11, 16, 24))
            self.draw_grid(painter)
            self.draw_boss(painter)
            self.draw_items(painter)
            self.draw_bullets(painter)
            self.draw_enemy_projectiles(painter)
            self.draw_lasers(painter)
            self.draw_player(painter)
            self.draw_crosshair(painter)
            self.draw_hud(painter)
            if self.game_over or self.victory:
                self.draw_center_message(painter, self.message)

        def draw_grid(self, painter):
            painter.setPen(QtGui.QPen(QtGui.QColor(36, 49, 68), 1))
            for x in range(0, self.width(), 50):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), 50):
                painter.drawLine(0, y, self.width(), y)

        def draw_boss(self, painter):
            rect = self.boss.rect()
            if self.figure_pixmap:
                painter.save()
                painter.setOpacity(0.9)
                painter.drawPixmap(rect.toRect(), self.figure_pixmap)
                painter.restore()
            else:
                painter.setBrush(QtGui.QColor(70, 80, 110))
                painter.setPen(QtGui.QPen(QtGui.QColor(170, 190, 230), 2))
                painter.drawRoundedRect(rect, 12, 12)
                painter.setPen(QtGui.QColor(230, 235, 245))
                painter.drawText(rect, QtCore.Qt.AlignCenter, "No figure loaded\nPlaceholder Boss")
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 90, 90), 2))
            painter.drawRoundedRect(rect, 8, 8)

        def draw_player(self, painter):
            painter.setBrush(QtGui.QColor(55, 220, 160))
            painter.setPen(QtGui.QPen(QtGui.QColor(210, 255, 235), 2))
            painter.drawEllipse(QtCore.QPointF(self.player.x, self.player.y), self.player.radius, self.player.radius)
            ux, uy = unit_vector(self.mouse_pos.x() - self.player.x, self.mouse_pos.y() - self.player.y)
            painter.drawLine(QtCore.QPointF(self.player.x, self.player.y), QtCore.QPointF(self.player.x + ux * 24, self.player.y + uy * 24))

        def draw_crosshair(self, painter):
            x, y = self.mouse_pos.x(), self.mouse_pos.y()
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 170, 40, 170), 1.5))
            painter.drawEllipse(QtCore.QPointF(x, y), 10, 10)
            painter.drawLine(QtCore.QPointF(x - 16, y), QtCore.QPointF(x + 16, y))
            painter.drawLine(QtCore.QPointF(x, y - 16), QtCore.QPointF(x, y + 16))

        def draw_bullets(self, painter):
            for bullet in self.bullets:
                if bullet.kind == "grenade":
                    painter.setBrush(QtGui.QColor(240, 190, 70))
                    painter.setPen(QtGui.QPen(QtGui.QColor(255, 235, 170), 1))
                else:
                    painter.setBrush(QtGui.QColor(110, 230, 255))
                    painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(bullet.x, bullet.y), bullet.radius, bullet.radius)
            now = time.monotonic()
            for x, y, r, expire in self.explosions:
                alpha = int(160 * max(0, (expire - now) / 0.25))
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 180, 40, alpha), 3))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 110, 20, max(0, alpha // 4))))
                painter.drawEllipse(QtCore.QPointF(x, y), r, r)

        def draw_enemy_projectiles(self, painter):
            for p in self.enemy_projectiles:
                if self.projectile_pixmap:
                    rect = QtCore.QRectF(p.x - p.radius, p.y - p.radius, p.radius * 2, p.radius * 2).toRect()
                    painter.drawPixmap(rect, self.projectile_pixmap)
                else:
                    painter.setBrush(QtGui.QColor(255, 80, 120))
                    painter.setPen(QtGui.QPen(QtGui.QColor(255, 180, 200), 1))
                    painter.drawRect(QtCore.QRectF(p.x - p.radius, p.y - p.radius, p.radius * 2, p.radius * 2))

        def draw_items(self, painter):
            colors = {
                "rifle_ammo": QtGui.QColor(80, 160, 255),
                "pistol_ammo": QtGui.QColor(130, 190, 255),
                "shotgun": QtGui.QColor(255, 180, 80),
                "grenade": QtGui.QColor(190, 255, 110),
                "health": QtGui.QColor(80, 240, 130),
            }
            for item in self.items:
                painter.setBrush(colors.get(item.kind, QtGui.QColor(255, 255, 255)))
                painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1))
                painter.drawRoundedRect(QtCore.QRectF(item.x - 12, item.y - 12, 24, 24), 5, 5)
                painter.setPen(QtGui.QColor(20, 20, 20))
                painter.drawText(QtCore.QRectF(item.x - 20, item.y - 7, 40, 14), QtCore.Qt.AlignCenter, item.kind[:2].upper())

        def draw_lasers(self, painter):
            now = time.monotonic()
            for laser in self.lasers:
                warning = now < laser.warning_until
                color = QtGui.QColor(255, 70, 70, 95 if warning else 210)
                width = 4 if warning else 22
                painter.setPen(QtGui.QPen(color, width))
                if laser.orientation == "vertical":
                    painter.drawLine(QtCore.QPointF(laser.pos, 0), QtCore.QPointF(laser.pos, self.height()))
                else:
                    painter.drawLine(QtCore.QPointF(0, laser.pos), QtCore.QPointF(self.width(), laser.pos))

        def draw_hud(self, painter):
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(25, 32, 44, 210))
            painter.drawRoundedRect(QtCore.QRectF(14, 12, 360, 88), 8, 8)
            self.draw_bar(painter, 28, 28, 150, 14, self.player.hp / 100.0, QtGui.QColor(65, 220, 120), "Player")
            self.draw_bar(painter, 28, 55, 300, 14, self.boss.hp / self.boss.max_hp, QtGui.QColor(255, 90, 90), f"Boss P{self.boss.phase}")
            weapon = self.current_weapon()
            reload_text = ""
            now = time.monotonic()
            if now < weapon.reloading_until:
                reload_text = f" reloading {weapon.reloading_until - now:.1f}s"
            painter.setPen(QtGui.QColor(235, 238, 245))
            painter.drawText(28, 91, f"{weapon.config.name.upper()}  {weapon.magazine}/{weapon.reserve}{reload_text}")
            painter.drawText(410, 28, "WASD move | Mouse/Space fire | Q/E weapon | R reload | 1-4 select | Esc close")

        def draw_bar(self, painter, x, y, w, h, frac, color, label):
            frac = clamp(frac, 0.0, 1.0)
            painter.setBrush(QtGui.QColor(60, 65, 75))
            painter.drawRect(x, y, w, h)
            painter.setBrush(color)
            painter.drawRect(x, y, int(w * frac), h)
            painter.setPen(QtGui.QColor(245, 245, 245))
            painter.drawText(x + w + 8, y + h, label)
            painter.setPen(QtCore.Qt.NoPen)

        def draw_center_message(self, painter, text):
            painter.setBrush(QtGui.QColor(0, 0, 0, 190))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(200, 270, self.width() - 400, 120), 12, 12)
            painter.setPen(QtGui.QColor(255, 255, 255))
            font = painter.font()
            font.setPointSize(18)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(220, 285, self.width() - 440, 90), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, text)


    class FigureBossGameWindow(QtWidgets.QDialog):
        def __init__(self, parent=None, figure_pixmap: QtGui.QPixmap | None = None):
            super().__init__(parent)
            self.setWindowTitle("Figure Boss Battle")
            self.resize(1000, 700)
            layout = QtWidgets.QVBoxLayout(self)
            self.canvas = GameCanvas(figure_pixmap=figure_pixmap, parent=self)
            layout.addWidget(self.canvas)

        def showEvent(self, event):
            super().showEvent(event)
            self.canvas.setFocus(QtCore.Qt.OtherFocusReason)


else:

    class FigureBossGameWindow:  # pragma: no cover - only used when PySide6 is missing
        def __init__(self, *args, **kwargs):
            raise RuntimeError(f"PySide6 is required for Figure Boss Battle: {PYSIDE6_IMPORT_ERROR}")


def main() -> None:
    if not PYSIDE6_AVAILABLE:
        raise RuntimeError(f"PySide6 is required for Figure Boss Battle: {PYSIDE6_IMPORT_ERROR}")
    app = QtWidgets.QApplication(sys.argv)
    figure_pixmap = None
    if len(sys.argv) > 1:
        image_path = Path(sys.argv[1])
        if image_path.exists():
            figure_pixmap = QtGui.QPixmap(str(image_path))
    window = FigureBossGameWindow(figure_pixmap=figure_pixmap)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
