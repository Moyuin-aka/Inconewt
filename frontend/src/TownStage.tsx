import { useEffect, useRef } from "react";
import Phaser from "phaser";
import type { NPC, World } from "./api";

type Direction = "down" | "left" | "right" | "up";

type ResidentActor = {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  bubble: Phaser.GameObjects.Text;
  prompt: Phaser.GameObjects.Text;
  location: string;
  textureKey: string;
};

type PlayerActor = {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  location: string;
};

export type StageCallbacks = {
  onResidentClick: (npcId: string, canTalk: boolean) => void;
  onTalkRequest: (npcId: string, x: number, y: number, location: string) => void;
  onPlayerMove: (x: number, y: number, location: string) => void;
  onNearbyChange: (npcId: string | null) => void;
  onScavengeRequest: (pointId: string) => void;
};

type TownDebug = {
  tweenCount: () => number;
  actorCount: () => number;
  worldSignature: () => string;
  playerPosition: () => { x: number; y: number; location: string } | null;
  nearbyNpc: () => string | null;
};

declare global {
  interface Window { __INCONNEWT_DEBUG__?: TownDebug; }
}

const WORLD_WIDTH = 1600;
const WORLD_HEIGHT = 1050;
const TALK_DISTANCE = 150;
const RESIDENT_IDS = ["momo", "lili", "xiaoke", "ajie"] as const;
const IDLE_FRAME: Record<Direction, number> = { down: 1, left: 4, right: 7, up: 10 };
const APPEARANCE_TINT = { moss: 0xadc78e, ember: 0xe7a26c, slate: 0xa8b6bf };

function worldSignature(world: World) {
  const residents = world.npcs
    .map((npc) => `${npc.id}:${npc.state.location}:${npc.state.action.type}:${npc.state.action.reason}:${npc.state.action.say}`)
    .join(",");
  const points = world.scavenge_points.map((point) => `${point.id}:${point.available}`).join(",");
  return [world.tick_index, world.weather, world.announcement, `${world.player.x}:${world.player.y}:${world.player.location}:${world.player.appearance}`, residents, points].join("|");
}

class InconnewtScene extends Phaser.Scene {
  private world?: World;
  private actors = new Map<string, ResidentActor>();
  private player?: PlayerActor;
  private scavengeMarkers = new Map<string, Phaser.GameObjects.Container>();
  private fog?: Phaser.GameObjects.TileSprite;
  private fogLayer?: Phaser.GameObjects.Container;
  private night?: Phaser.GameObjects.Rectangle;
  private fire?: Phaser.GameObjects.Arc;
  private boundaryGlow?: Phaser.GameObjects.Arc;
  private boardMarker?: Phaser.GameObjects.Rectangle;
  private keys?: Record<"up" | "down" | "left" | "right" | "interact", Phaser.Input.Keyboard.Key>;
  private clickTarget?: Phaser.Math.Vector2;
  private nearbyNpcId: string | null = null;
  private lastAnnouncement = "";
  private lastSignature = "";
  private lastNightAlpha?: number;
  private lastFogAlpha?: number;
  private lastPersistAt = 0;
  private lastProximityAt = 0;
  private playerMoved = false;
  private ignoreGroundClick = false;
  private ready = false;
  private callbacks: StageCallbacks;

  constructor(callbacks: StageCallbacks, initialWorld: World) {
    super("inconnewt-town-v3");
    this.callbacks = callbacks;
    this.world = initialWorld;
  }

  setCallbacks(callbacks: StageCallbacks) { this.callbacks = callbacks; }

  preload() {
    this.load.image("town-v3", "/assets/town-v3.webp");
    RESIDENT_IDS.forEach((id) => {
      this.load.spritesheet(`sprite-${id}`, `/assets/sprite-${id}.png`, { frameWidth: 16, frameHeight: 16 });
    });
  }

  create() {
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.drawTown();
    this.createAnimations();
    this.createPlayer();
    this.configureControls();
    this.ready = true;
    window.__INCONNEWT_DEBUG__ = {
      tweenCount: () => this.tweens.getTweens().length,
      actorCount: () => this.actors.size,
      worldSignature: () => this.lastSignature,
      playerPosition: () => this.player ? { x: Math.round(this.player.container.x), y: Math.round(this.player.container.y), location: this.player.location } : null,
      nearbyNpc: () => this.nearbyNpcId,
    };
    if (this.world) this.syncWorld(this.world, true);
  }

  update(_: number, delta: number) {
    if (!this.player || !this.keys || !this.world) return;
    const horizontal = Number(this.keys.right.isDown) - Number(this.keys.left.isDown);
    const vertical = Number(this.keys.down.isDown) - Number(this.keys.up.isDown);
    const usingKeyboard = horizontal !== 0 || vertical !== 0;
    let dx = horizontal;
    let dy = vertical;

    if (usingKeyboard) {
      this.clickTarget = undefined;
    } else if (this.clickTarget) {
      const distance = Phaser.Math.Distance.Between(
        this.player.container.x, this.player.container.y, this.clickTarget.x, this.clickTarget.y,
      );
      if (distance <= 7) this.clickTarget = undefined;
      else {
        dx = (this.clickTarget.x - this.player.container.x) / distance;
        dy = (this.clickTarget.y - this.player.container.y) / distance;
      }
    }

    const moving = dx !== 0 || dy !== 0;
    if (moving) {
      const length = Math.hypot(dx, dy) || 1;
      const speed = 185;
      this.player.container.x = Phaser.Math.Clamp(this.player.container.x + (dx / length) * speed * delta / 1000, 35, WORLD_WIDTH - 35);
      this.player.container.y = Phaser.Math.Clamp(this.player.container.y + (dy / length) * speed * delta / 1000, 55, WORLD_HEIGHT - 25);
      this.player.container.setDepth(this.player.container.y + 150);
      const direction = this.directionFor(dx, dy);
      const animation = `player-walk-${direction}`;
      if (this.player.sprite.anims.currentAnim?.key !== animation) this.player.sprite.play(animation);
      this.playerMoved = true;
    } else if (this.player.sprite.anims.isPlaying) {
      const direction = this.player.sprite.anims.currentAnim?.key.split("-").pop() as Direction | undefined;
      this.player.sprite.stop().setFrame(IDLE_FRAME[direction ?? "down"]);
    }

    const now = this.time.now;
    if (now - this.lastProximityAt > 120) {
      this.updateProximity();
      this.lastProximityAt = now;
    }
    if (this.playerMoved && now - this.lastPersistAt > 650) {
      this.persistPlayerPosition();
      this.lastPersistAt = now;
      this.playerMoved = moving;
    }
  }

  setWorld(world: World) {
    const signature = worldSignature(world);
    if (this.ready && signature === this.lastSignature) return;
    this.world = world;
    if (this.ready) this.syncWorld(world, false);
  }

  private drawTown() {
    this.add.image(WORLD_WIDTH / 2, WORLD_HEIGHT / 2, "town-v3").setDisplaySize(WORLD_WIDTH, WORLD_HEIGHT).setDepth(0);
    this.world?.locations.forEach((location) => {
      this.add.text(location.x, location.y - 72, `${location.symbol}  ${location.name}`, {
        fontFamily: 'Georgia, "Songti SC", serif', fontSize: "14px", color: "#f4ecd7",
        backgroundColor: "rgba(34,39,31,0.86)", padding: { x: 9, y: 5 }, stroke: "#30352c", strokeThickness: 2,
      }).setOrigin(0.5).setDepth(location.y + 120);
    });

    this.boardMarker = this.add.rectangle(620, 525, 72, 58, 0xdcc68d, 0).setStrokeStyle(3, 0xf2d58b, 0).setDepth(1250);
    this.fire = this.add.circle(690, 675, 29, 0xf2a34f, 0.18).setDepth(1100);
    // alpha 由昼夜状态独占控制，常驻补间只呼吸 scale，避免相互抢值。
    this.tweens.add({ targets: this.fire, scale: 1.45, duration: 1250, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
    this.boundaryGlow = this.add.circle(1400, 175, 46, 0x80dbe4, 0.09).setDepth(1050);
    this.tweens.add({ targets: this.boundaryGlow, scale: 1.32, duration: 1900, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });

    const fogTexture = this.add.graphics();
    fogTexture.fillStyle(0xe4e4d7, 0.24);
    fogTexture.fillCircle(70, 55, 58).fillCircle(155, 70, 72).fillCircle(235, 45, 65);
    fogTexture.generateTexture("fog-bank-v3", 300, 130);
    fogTexture.destroy();
    this.fog = this.add.tileSprite(0, 0, WORLD_WIDTH + 100, WORLD_HEIGHT + 70, "fog-bank-v3").setOrigin(0);
    this.fogLayer = this.add.container(0, 0, [this.fog]).setAlpha(0).setDepth(1900);
    this.tweens.add({ targets: this.fog, tilePositionX: 300, duration: 26000, repeat: -1 });

    this.night = this.add.rectangle(WORLD_WIDTH / 2, WORLD_HEIGHT / 2, WORLD_WIDTH, WORLD_HEIGHT, 0x17243a, 0)
      .setBlendMode(Phaser.BlendModes.MULTIPLY).setDepth(1800);

    const grain = this.add.graphics();
    for (let index = 0; index < 90; index += 1) {
      grain.fillStyle(index % 3 === 0 ? 0xf3eddc : 0x2b3028, 0.16);
      grain.fillRect((index * 37) % 128, (index * 71) % 128, index % 5 === 0 ? 2 : 1, 1);
    }
    grain.generateTexture("paper-grain-v3", 128, 128);
    grain.destroy();
    this.add.tileSprite(WORLD_WIDTH / 2, WORLD_HEIGHT / 2, WORLD_WIDTH, WORLD_HEIGHT, "paper-grain-v3").setAlpha(0.07).setDepth(2000);
  }

  private createAnimations() {
    RESIDENT_IDS.forEach((id) => this.createDirectionalAnimations(`sprite-${id}`, `sprite-${id}`));
    this.createDirectionalAnimations("sprite-momo", "player");
  }

  private createDirectionalAnimations(textureKey: string, prefix: string) {
    (["down", "left", "right", "up"] as Direction[]).forEach((direction, index) => {
      const key = `${prefix}-walk-${direction}`;
      if (!this.anims.exists(key)) this.anims.create({
        key, frames: this.anims.generateFrameNumbers(textureKey, { start: index * 3, end: index * 3 + 2 }), frameRate: 8, repeat: -1,
      });
    });
  }

  private createPlayer() {
    if (!this.world) return;
    const sprite = this.add.sprite(0, 0, "sprite-momo", IDLE_FRAME.down).setOrigin(0.5, 1).setScale(3.2);
    sprite.setTint(APPEARANCE_TINT[this.world.player.appearance]);
    const ring = this.add.ellipse(0, 2, 42, 18, 0xe8d89f, 0.15).setStrokeStyle(2, 0xe8d89f, 0.9);
    const name = this.add.text(0, 8, "你 · 外来者", {
      fontFamily: 'Georgia, "Songti SC", serif', fontSize: "12px", color: "#fff7e5", stroke: "#263027", strokeThickness: 4,
    }).setOrigin(0.5, 0);
    const container = this.add.container(this.world.player.x, this.world.player.y, [ring, sprite, name])
      .setDepth(this.world.player.y + 150).setSize(64, 85);
    this.player = { container, sprite, location: this.world.player.location };
    this.cameras.main.startFollow(container, true, 0.09, 0.09);
    this.cameras.main.setDeadzone(110, 80);
  }

  private configureControls() {
    if (!this.input.keyboard) return;
    this.keys = {
      up: this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.W),
      down: this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.S),
      left: this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.A),
      right: this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.D),
      interact: this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.E),
    };
    this.keys.interact.on("down", () => {
      if (this.nearbyNpcId) this.requestTalk(this.nearbyNpcId);
    });
    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (this.ignoreGroundClick) {
        this.ignoreGroundClick = false;
        return;
      }
      this.clickTarget = new Phaser.Math.Vector2(pointer.worldX, pointer.worldY);
    });
  }

  private syncWorld(world: World, initial: boolean) {
    this.lastSignature = worldSignature(world);
    const locations = new Map(world.locations.map((location) => [location.id, location]));
    world.npcs.forEach((npc, index) => {
      const destination = locations.get(npc.state.location) ?? world.locations[index];
      let actor = this.actors.get(npc.id);
      if (!actor) {
        actor = this.createActor(npc, destination.x + (index % 2) * 34 - 17, destination.y + 55);
        this.actors.set(npc.id, actor);
      }
      const nextBubble = this.bubbleText(npc);
      if (actor.bubble.text !== nextBubble) actor.bubble.setText(nextBubble);
      actor.bubble.setBackgroundColor(npc.state.action.source === "deepseek" ? "#dbe6d2" : "#eee3cc");
      if (!initial && actor.location !== npc.state.location) this.walkActor(actor, destination.x + (index % 2) * 34 - 17, destination.y + 55);
      actor.location = npc.state.location;
    });
    if (this.player) {
      this.player.sprite.setTint(APPEARANCE_TINT[world.player.appearance]);
      if (!this.playerMoved && Phaser.Math.Distance.Between(this.player.container.x, this.player.container.y, world.player.x, world.player.y) > 12) {
        this.player.container.setPosition(world.player.x, world.player.y).setDepth(world.player.y + 150);
        this.player.location = world.player.location;
      }
    }
    this.syncScavengeMarkers(world);

    const hour = world.minute / 60;
    const nightAlpha = hour >= 20 || hour < 6 ? 0.58 : hour >= 18 ? (hour - 18) * 0.24 : 0;
    if (this.night && nightAlpha !== this.lastNightAlpha) {
      this.tweens.killTweensOf(this.night);
      if (initial) this.night.setAlpha(nightAlpha);
      else this.tweens.add({ targets: this.night, alpha: nightAlpha, duration: 850 });
      this.lastNightAlpha = nightAlpha;
    }
    const fogAlpha = world.weather === "雾" ? 0.66 : 0;
    if (this.fogLayer && fogAlpha !== this.lastFogAlpha) {
      this.tweens.killTweensOf(this.fogLayer);
      if (initial) this.fogLayer.setAlpha(fogAlpha);
      else this.tweens.add({ targets: this.fogLayer, alpha: fogAlpha, duration: 1200 });
      this.lastFogAlpha = fogAlpha;
    }
    this.fire?.setAlpha(hour >= 18 || hour < 6 ? 0.56 : 0.16);
    this.boundaryGlow?.setAlpha(hour >= 18 || hour < 6 ? 0.28 : 0.08);
    if (this.lastAnnouncement && this.lastAnnouncement !== world.announcement && this.boardMarker) {
      this.tweens.killTweensOf(this.boardMarker);
      this.boardMarker.setAlpha(0).setScale(1).setAngle(0);
      this.tweens.add({
        targets: this.boardMarker, alpha: { from: 0, to: 0.9 }, scale: 1.35, angle: 2,
        duration: 190, yoyo: true, repeat: 2,
        onComplete: () => this.boardMarker?.setAlpha(0).setScale(1).setAngle(0),
      });
    }
    this.lastAnnouncement = world.announcement;
  }

  private createActor(npc: NPC, x: number, y: number): ResidentActor {
    const textureKey = `sprite-${npc.id}`;
    const sprite = this.add.sprite(0, 0, textureKey, IDLE_FRAME.down).setOrigin(0.5, 1).setScale(3);
    const name = this.add.text(0, 7, npc.profile.name, {
      fontFamily: '"PingFang SC", sans-serif', fontSize: "12px", color: "#fff7e5", stroke: "#263027", strokeThickness: 4,
    }).setOrigin(0.5, 0);
    const bubble = this.add.text(0, -61, this.bubbleText(npc), {
      fontFamily: '"PingFang SC", sans-serif', fontSize: "11px", color: "#2c3029", padding: { x: 8, y: 5 }, align: "center",
    }).setOrigin(0.5, 1).setBackgroundColor("#eee3cc").setAlpha(0.94);
    const prompt = this.add.text(0, -91, "E  交谈", {
      fontFamily: '"PingFang SC", sans-serif', fontSize: "11px", color: "#263027", backgroundColor: "#f0d890", padding: { x: 8, y: 4 },
    }).setOrigin(0.5, 1).setVisible(false);
    const container = this.add.container(x, y, [sprite, name, bubble, prompt])
      .setSize(94, 105).setDepth(y + 100).setInteractive({ useHandCursor: true });
    container.on("pointerover", () => {
      this.tweens.killTweensOf(container);
      this.tweens.add({ targets: container, scale: 1.08, duration: 120 });
    });
    container.on("pointerout", () => {
      this.tweens.killTweensOf(container);
      this.tweens.add({ targets: container, scale: 1, duration: 120 });
    });
    container.on("pointerdown", () => {
      this.ignoreGroundClick = true;
      const canTalk = this.nearbyNpcId === npc.id;
      if (canTalk) this.requestTalk(npc.id);
      else this.callbacks.onResidentClick(npc.id, false);
    });
    const actor = { container, sprite, bubble, prompt, location: npc.state.location, textureKey };
    this.startBubbleFloat(actor);
    return actor;
  }

  private syncScavengeMarkers(world: World) {
    world.scavenge_points.forEach((point) => {
      let marker = this.scavengeMarkers.get(point.id);
      if (!marker) {
        const pulse = this.add.circle(0, 0, 15, 0xe8d89f, 0.16).setStrokeStyle(2, 0xe8d89f, 0.9);
        const text = this.add.text(0, -24, point.label, {
          fontFamily: 'Georgia, "Songti SC", serif', fontSize: "10px", color: "#fff4d5", backgroundColor: "rgba(31,38,30,.86)", padding: { x: 7, y: 4 },
        }).setOrigin(0.5, 1);
        marker = this.add.container(point.x, point.y, [pulse, text]).setSize(90, 60).setDepth(point.y + 80).setInteractive({ useHandCursor: true });
        marker.on("pointerdown", () => {
          this.ignoreGroundClick = true;
          if (this.player && Phaser.Math.Distance.Between(this.player.container.x, this.player.container.y, point.x, point.y) <= 130) {
            this.callbacks.onScavengeRequest(point.id);
          } else {
            this.clickTarget = new Phaser.Math.Vector2(point.x, point.y);
          }
        });
        this.tweens.add({ targets: pulse, scale: 1.35, alpha: 0.04, duration: 1000, yoyo: true, repeat: -1 });
        this.scavengeMarkers.set(point.id, marker);
      }
      marker.setVisible(point.available).setActive(point.available);
    });
  }

  private updateProximity() {
    if (!this.player || !this.world) return;
    let closestId: string | null = null;
    let closestDistance = Number.POSITIVE_INFINITY;
    for (const [id, actor] of this.actors) {
      const distance = Phaser.Math.Distance.Between(this.player!.container.x, this.player!.container.y, actor.container.x, actor.container.y);
      const sameLocation = this.player!.location === actor.location;
      actor.prompt.setVisible(sameLocation && distance <= TALK_DISTANCE);
      if (sameLocation && distance <= TALK_DISTANCE && distance < closestDistance) {
        closestId = id;
        closestDistance = distance;
      }
    }
    const next = closestId;
    if (next !== this.nearbyNpcId) {
      this.nearbyNpcId = next;
      this.callbacks.onNearbyChange(next);
    }
  }

  private persistPlayerPosition() {
    if (!this.player || !this.world) return;
    const nearest = [...this.world.locations].sort((first, second) => (
      Phaser.Math.Distance.Squared(this.player!.container.x, this.player!.container.y, first.x, first.y)
      - Phaser.Math.Distance.Squared(this.player!.container.x, this.player!.container.y, second.x, second.y)
    ))[0];
    if (!nearest) return;
    this.player.location = nearest.id;
    this.callbacks.onPlayerMove(Math.round(this.player.container.x), Math.round(this.player.container.y), nearest.id);
  }

  private requestTalk(npcId: string) {
    if (!this.player) return;
    this.callbacks.onTalkRequest(
      npcId,
      Math.round(this.player.container.x),
      Math.round(this.player.container.y),
      this.player.location,
    );
  }

  private walkActor(actor: ResidentActor, x: number, y: number) {
    this.tweens.killTweensOf(actor.container);
    this.tweens.killTweensOf(actor.sprite);
    this.tweens.killTweensOf(actor.bubble);
    actor.sprite.stop().setAngle(0);
    actor.container.setScale(1);
    const dx = x - actor.container.x;
    const dy = y - actor.container.y;
    const direction = this.directionFor(dx, dy);
    actor.sprite.play(`${actor.textureKey}-walk-${direction}`);
    actor.bubble.setAlpha(0);
    const middleX = (actor.container.x + x) / 2 + dy * 0.08;
    const middleY = (actor.container.y + y) / 2;
    this.tweens.chain({
      targets: actor.container,
      tweens: [{ x: middleX, y: middleY, duration: 700, ease: "Sine.easeInOut" }, { x, y, duration: 700, ease: "Sine.easeInOut" }],
      onUpdate: () => actor.container.setDepth(actor.container.y + 100),
      onComplete: () => { actor.sprite.stop().setFrame(IDLE_FRAME[direction]).setAngle(0); this.startBubbleFloat(actor); },
    });
    this.tweens.add({ targets: actor.bubble, alpha: 0.94, duration: 420, delay: 850 });
  }

  private startBubbleFloat(actor: ResidentActor) {
    this.tweens.killTweensOf(actor.bubble);
    actor.bubble.setY(-61).setAlpha(0.94);
    this.tweens.add({ targets: actor.bubble, y: -66, duration: 1050, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
  }

  private directionFor(dx: number, dy: number): Direction {
    return Math.abs(dx) > Math.abs(dy) ? (dx >= 0 ? "right" : "left") : (dy >= 0 ? "down" : "up");
  }

  private bubbleText(npc: NPC) {
    const text = npc.state.action.say || npc.state.action.reason;
    return text.length > 25 ? `${text.slice(0, 25)}…` : text;
  }
}

export function TownStage({ world, callbacks }: { world: World; callbacks: StageCallbacks }) {
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<Phaser.Game>();
  const scene = useRef<InconnewtScene>();

  useEffect(() => {
    if (!host.current) return;
    scene.current = new InconnewtScene(callbacks, world);
    game.current = new Phaser.Game({
      type: Phaser.WEBGL, parent: host.current, width: 1000, height: 650, backgroundColor: "#747961", scene: scene.current,
      render: { antialias: false, pixelArt: true, roundPixels: true, powerPreference: "high-performance" },
      scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    });
    scene.current.setWorld(world);
    return () => {
      if (window.__INCONNEWT_DEBUG__) delete window.__INCONNEWT_DEBUG__;
      game.current?.destroy(true);
      game.current = undefined;
    };
  }, []);

  useEffect(() => { scene.current?.setCallbacks(callbacks); }, [callbacks]);
  useEffect(() => { scene.current?.setWorld(world); }, [world]);
  return <div ref={host} className="town-stage" aria-label="新螈镇可探索游戏场景，支持 WASD 与点击移动" />;
}
