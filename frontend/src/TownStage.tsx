import { useEffect, useRef } from "react";
import Phaser from "phaser";
import type { NPC, World } from "./api";

type Direction = "down" | "left" | "right" | "up";

type ResidentActor = {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  bubble: Phaser.GameObjects.Text;
  location: string;
  textureKey: string;
};

type TownDebug = {
  tweenCount: () => number;
  actorCount: () => number;
  worldSignature: () => string;
};

declare global {
  interface Window {
    __INCONNEWT_DEBUG__?: TownDebug;
  }
}

const RESIDENT_IDS = ["momo", "lili", "xiaoke", "ajie"] as const;
const IDLE_FRAME: Record<Direction, number> = { down: 1, left: 4, right: 7, up: 10 };

function worldSignature(world: World) {
  const positions = world.npcs.map((npc) => `${npc.id}:${npc.state.location}`).join(",");
  return [world.tick_index, world.weather, world.announcement, positions].join("|");
}

class InconnewtScene extends Phaser.Scene {
  private world?: World;
  private actors = new Map<string, ResidentActor>();
  private fog?: Phaser.GameObjects.TileSprite;
  private fogLayer?: Phaser.GameObjects.Container;
  private night?: Phaser.GameObjects.Rectangle;
  private fire?: Phaser.GameObjects.Arc;
  private boardMarker?: Phaser.GameObjects.Rectangle;
  private lastAnnouncement = "";
  private lastSignature = "";
  private lastNightAlpha?: number;
  private lastFogAlpha?: number;
  private ready = false;
  private onResidentClick: (npcId: string) => void;

  constructor(onResidentClick: (npcId: string) => void, initialWorld: World) {
    super("inconnewt-town");
    this.onResidentClick = onResidentClick;
    this.world = initialWorld;
  }

  preload() {
    this.load.image("town-v21", "/assets/town-v21.webp");
    RESIDENT_IDS.forEach((id) => {
      this.load.spritesheet(`sprite-${id}`, `/assets/sprite-${id}.png`, {
        frameWidth: 16,
        frameHeight: 16,
      });
    });
  }

  create() {
    this.drawTown();
    this.createResidentAnimations();
    this.ready = true;
    window.__INCONNEWT_DEBUG__ = {
      tweenCount: () => this.tweens.getTweens().length,
      actorCount: () => this.actors.size,
      worldSignature: () => this.lastSignature,
    };
    if (this.world) this.syncWorld(this.world, true);
  }

  setWorld(world: World) {
    const signature = worldSignature(world);
    if (this.ready && signature === this.lastSignature) return;
    this.world = world;
    if (this.ready) this.syncWorld(world, false);
  }

  private drawTown() {
    this.add.image(500, 325, "town-v21").setDisplaySize(1000, 650).setDepth(0);

    this.world?.locations.forEach((location) => {
      this.add.text(location.x, location.y - 58, `${location.symbol}  ${location.name}`, {
        fontFamily: 'Georgia, "Songti SC", serif',
        fontSize: "14px",
        color: "#f4ecd7",
        backgroundColor: "rgba(34,39,31,0.82)",
        padding: { x: 9, y: 5 },
        stroke: "#30352c",
        strokeThickness: 2,
      }).setOrigin(0.5).setDepth(1300);
    });

    // 底图已经包含公告板和火塘；透明标记只负责触发反馈演出。
    this.boardMarker = this.add.rectangle(420, 445, 72, 58, 0xdcc68d, 0)
      .setStrokeStyle(3, 0xf2d58b, 0)
      .setDepth(1250);
    this.fire = this.add.circle(455, 560, 29, 0xf2a34f, 0.16).setDepth(1100);
    this.tweens.add({
      targets: this.fire,
      scale: 1.45,
      alpha: 0.05,
      duration: 1250,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });

    const fogTexture = this.add.graphics();
    fogTexture.fillStyle(0xe4e4d7, 0.24);
    fogTexture.fillCircle(70, 55, 58).fillCircle(155, 70, 72).fillCircle(235, 45, 65);
    fogTexture.generateTexture("fog-bank", 300, 130);
    fogTexture.destroy();
    this.fog = this.add.tileSprite(0, 0, 1100, 720, "fog-bank").setOrigin(0);
    this.fogLayer = this.add.container(0, 0, [this.fog]).setAlpha(0).setDepth(1900);
    this.tweens.add({ targets: this.fog, tilePositionX: 300, duration: 26000, repeat: -1 });

    this.night = this.add.rectangle(500, 325, 1000, 650, 0x17243a, 0)
      .setBlendMode(Phaser.BlendModes.MULTIPLY)
      .setDepth(1800);

    // 纸纹放进 WebGL 场景，避免 DOM mix-blend-mode 每帧重混整张画布。
    const grain = this.add.graphics();
    for (let index = 0; index < 90; index += 1) {
      const x = (index * 37) % 128;
      const y = (index * 71) % 128;
      grain.fillStyle(index % 3 === 0 ? 0xf3eddc : 0x2b3028, 0.16);
      grain.fillRect(x, y, index % 5 === 0 ? 2 : 1, 1);
    }
    grain.generateTexture("paper-grain", 128, 128);
    grain.destroy();
    this.add.tileSprite(500, 325, 1000, 650, "paper-grain").setAlpha(0.08).setDepth(2000);
  }

  private createResidentAnimations() {
    RESIDENT_IDS.forEach((id) => {
      const textureKey = `sprite-${id}`;
      (["down", "left", "right", "up"] as Direction[]).forEach((direction, index) => {
        const key = `${textureKey}-walk-${direction}`;
        if (this.anims.exists(key)) return;
        this.anims.create({
          key,
          frames: this.anims.generateFrameNumbers(textureKey, { start: index * 3, end: index * 3 + 2 }),
          frameRate: 7,
          repeat: -1,
        });
      });
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
      if (!initial && actor.location !== npc.state.location) {
        this.walkActor(actor, destination.x + (index % 2) * 34 - 17, destination.y + 55);
      }
      actor.location = npc.state.location;
    });

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

    if (this.fire) this.fire.setAlpha(hour >= 18 || hour < 6 ? 0.56 : 0.16);
    if (this.lastAnnouncement && this.lastAnnouncement !== world.announcement && this.boardMarker) {
      this.tweens.killTweensOf(this.boardMarker);
      this.boardMarker.setAlpha(0).setScale(1).setAngle(0);
      this.tweens.add({
        targets: this.boardMarker,
        alpha: { from: 0, to: 0.9 },
        scale: 1.35,
        angle: 2,
        duration: 190,
        yoyo: true,
        repeat: 2,
        onComplete: () => this.boardMarker?.setAlpha(0).setScale(1).setAngle(0),
      });
    }
    this.lastAnnouncement = world.announcement;
  }

  private createActor(npc: NPC, x: number, y: number): ResidentActor {
    const textureKey = `sprite-${npc.id}`;
    const sprite = this.add.sprite(0, 0, textureKey, IDLE_FRAME.down).setOrigin(0.5, 1).setScale(3);
    const name = this.add.text(0, 7, npc.profile.name, {
      fontFamily: '"PingFang SC", sans-serif',
      fontSize: "12px",
      color: "#fff7e5",
      stroke: "#263027",
      strokeThickness: 4,
    }).setOrigin(0.5, 0);
    const bubble = this.add.text(0, -61, this.bubbleText(npc), {
      fontFamily: '"PingFang SC", sans-serif',
      fontSize: "11px",
      color: "#2c3029",
      padding: { x: 8, y: 5 },
      align: "center",
    }).setOrigin(0.5, 1).setBackgroundColor("#eee3cc").setAlpha(0.94);
    const container = this.add.container(x, y, [sprite, name, bubble])
      .setSize(94, 105)
      .setDepth(y + 100)
      .setInteractive({ useHandCursor: true });
    container.on("pointerover", () => this.tweens.add({ targets: container, scale: 1.08, duration: 120 }));
    container.on("pointerout", () => this.tweens.add({ targets: container, scale: 1, duration: 120 }));
    container.on("pointerdown", () => this.onResidentClick(npc.id));
    const actor = { container, sprite, bubble, location: npc.state.location, textureKey };
    this.startBubbleFloat(actor);
    return actor;
  }

  private startBubbleFloat(actor: ResidentActor) {
    this.tweens.killTweensOf(actor.bubble);
    actor.bubble.setY(-61).setAlpha(0.94);
    this.tweens.add({
      targets: actor.bubble,
      y: -66,
      duration: 1050,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
  }

  private walkActor(actor: ResidentActor, x: number, y: number) {
    this.tweens.killTweensOf(actor.container);
    this.tweens.killTweensOf(actor.sprite);
    this.tweens.killTweensOf(actor.bubble);
    actor.sprite.stop().setAngle(0);
    actor.container.setScale(1);
    const dx = x - actor.container.x;
    const dy = y - actor.container.y;
    const direction: Direction = Math.abs(dx) > Math.abs(dy)
      ? (dx >= 0 ? "right" : "left")
      : (dy >= 0 ? "down" : "up");
    actor.sprite.play(`${actor.textureKey}-walk-${direction}`);
    actor.bubble.setAlpha(0);

    const middleX = (actor.container.x + x) / 2 + dy * 0.08;
    const middleY = (actor.container.y + y) / 2;
    this.tweens.chain({
      targets: actor.container,
      tweens: [
        { x: middleX, y: middleY, duration: 700, ease: "Sine.easeInOut" },
        { x, y, duration: 700, ease: "Sine.easeInOut" },
      ],
      onUpdate: () => actor.container.setDepth(actor.container.y + 100),
      onComplete: () => {
        actor.sprite.stop().setFrame(IDLE_FRAME[direction]).setAngle(0);
        this.startBubbleFloat(actor);
      },
    });
    this.tweens.add({ targets: actor.bubble, alpha: 0.94, duration: 420, delay: 850 });
  }

  private bubbleText(npc: NPC) {
    return npc.state.action.reason.length > 25
      ? `${npc.state.action.reason.slice(0, 25)}…`
      : npc.state.action.reason;
  }
}

export function TownStage({ world, onResidentClick }: { world: World; onResidentClick: (npcId: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<Phaser.Game>();
  const scene = useRef<InconnewtScene>();

  useEffect(() => {
    if (!host.current) return;
    scene.current = new InconnewtScene(onResidentClick, world);
    game.current = new Phaser.Game({
      type: Phaser.WEBGL,
      parent: host.current,
      width: 1000,
      height: 650,
      backgroundColor: "#747961",
      scene: scene.current,
      render: {
        antialias: false,
        pixelArt: true,
        roundPixels: true,
        powerPreference: "high-performance",
      },
      scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    });
    scene.current.setWorld(world);
    return () => {
      if (window.__INCONNEWT_DEBUG__) delete window.__INCONNEWT_DEBUG__;
      game.current?.destroy(true);
      game.current = undefined;
    };
  }, []);

  useEffect(() => { scene.current?.setWorld(world); }, [world]);
  return <div ref={host} className="town-stage" aria-label="新螈镇实时游戏场景" />;
}
