import { useEffect, useRef } from "react";
import Phaser from "phaser";
import type { NPC, World } from "./api";

type ResidentActor = {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  bubble: Phaser.GameObjects.Text;
  location: string;
};

const COLORS: Record<string, number> = {
  store: 0x8f745c,
  repair: 0x8b654b,
  tower: 0x56615d,
  greenhouse: 0x658057,
  square: 0x668381,
};

class InconnewtScene extends Phaser.Scene {
  private world?: World;
  private actors = new Map<string, ResidentActor>();
  private fog?: Phaser.GameObjects.TileSprite;
  private night?: Phaser.GameObjects.Rectangle;
  private fire?: Phaser.GameObjects.Arc;
  private board?: Phaser.GameObjects.Rectangle;
  private lastAnnouncement = "";
  private ready = false;
  private onResidentClick: (npcId: string) => void;

  constructor(onResidentClick: (npcId: string) => void, initialWorld: World) {
    super("inconnewt-town");
    this.onResidentClick = onResidentClick;
    this.world = initialWorld;
  }

  create() {
    this.drawTown();
    this.ready = true;
    if (this.world) this.syncWorld(this.world, true);
  }

  setWorld(world: World) {
    this.world = world;
    if (this.ready) this.syncWorld(world, false);
  }

  private drawTown() {
    const ground = this.add.graphics();
    ground.fillStyle(0x747961, 1).fillRect(0, 0, 1000, 650);
    ground.fillStyle(0x88906e, 0.42);
    for (let index = 0; index < 90; index += 1) {
      const x = (index * 83) % 1000;
      const y = (index * 137) % 650;
      ground.fillCircle(x, y, 2 + (index % 4));
    }
    ground.lineStyle(42, 0xb0a88c, 0.38);
    ground.beginPath().moveTo(185, 205).lineTo(390, 455).lineTo(785, 470).strokePath();
    ground.beginPath().moveTo(390, 455).lineTo(510, 140).lineTo(820, 190).strokePath();
    ground.lineStyle(2, 0xddd3b6, 0.16);
    ground.strokeCircle(390, 455, 96);

    this.add.ellipse(390, 472, 170, 76, 0x4d7370, 0.62).setStrokeStyle(2, 0xaac1ae, 0.35);
    this.add.circle(390, 440, 5, 0xc5d59d, 0.75);
    this.add.text(343, 490, "水潭里的蝾螈", { fontFamily: "serif", fontSize: "12px", color: "#d8ddc9" });

    const buildingStyles: Record<string, { width: number; height: number }> = {
      store: { width: 180, height: 105 }, repair: { width: 170, height: 92 }, tower: { width: 118, height: 145 },
      greenhouse: { width: 190, height: 110 }, square: { width: 150, height: 70 },
    };
    this.world?.locations.forEach((location) => {
      const size = buildingStyles[location.id];
      const building = this.add.rectangle(location.x, location.y, size.width, size.height, COLORS[location.id], 0.96)
        .setStrokeStyle(2, 0xe8dfc7, 0.6);
      building.setDepth(location.y - 80);
      if (location.id === "greenhouse") {
        for (let x = -65; x <= 65; x += 32) this.add.line(location.x, location.y, x, -48, x, 48, 0xc8d5be, 0.32).setDepth(location.y - 79);
      }
      if (location.id === "tower") {
        this.add.triangle(location.x, location.y - 98, 0, 42, 58, 42, 29, 0, 0x39443f, 1).setDepth(location.y - 79);
      }
      this.add.text(location.x, location.y - size.height / 2 - 27, `${location.symbol}  ${location.name}`, {
        fontFamily: 'Georgia, "Songti SC", serif', fontSize: "15px", color: "#f1ead8", stroke: "#30352c", strokeThickness: 3,
      }).setOrigin(0.5).setDepth(900);
    });

    this.board = this.add.rectangle(465, 420, 34, 46, 0x403d31, 1).setStrokeStyle(2, 0xd7cdae, 0.7).setDepth(480);
    this.add.text(465, 420, "告", { fontFamily: "serif", fontSize: "12px", color: "#eadfca" }).setOrigin(0.5).setDepth(481);

    this.fire = this.add.circle(452, 468, 24, 0xe59b4c, 0.4).setDepth(470);
    this.add.circle(452, 468, 7, 0xffc56c, 0.95).setDepth(471);
    this.tweens.add({ targets: this.fire, scale: 1.5, alpha: 0.12, duration: 1200, yoyo: true, repeat: -1 });

    const fogTexture = this.add.graphics();
    fogTexture.fillStyle(0xdde1d4, 0.32);
    fogTexture.fillCircle(70, 55, 58).fillCircle(155, 70, 72).fillCircle(235, 45, 65);
    fogTexture.generateTexture("fog-bank", 300, 130);
    fogTexture.destroy();
    this.fog = this.add.tileSprite(500, 325, 1100, 720, "fog-bank").setAlpha(0).setDepth(1900);
    this.tweens.add({ targets: this.fog, tilePositionX: 300, duration: 26000, repeat: -1 });
    this.night = this.add.rectangle(500, 325, 1000, 650, 0x16233a, 0).setBlendMode(Phaser.BlendModes.MULTIPLY).setDepth(1800);
    this.add.rectangle(500, 325, 1000, 650, 0x2e3329, 0.08).setDepth(2000).setBlendMode(Phaser.BlendModes.MULTIPLY);
  }

  private syncWorld(world: World, initial: boolean) {
    const locations = new Map(world.locations.map((location) => [location.id, location]));
    world.npcs.forEach((npc, index) => {
      const destination = locations.get(npc.state.location) ?? world.locations[index];
      let actor = this.actors.get(npc.id);
      if (!actor) {
        actor = this.createActor(npc, destination.x + (index % 2) * 34 - 17, destination.y + 65);
        this.actors.set(npc.id, actor);
      }
      actor.bubble.setText(this.bubbleText(npc));
      actor.bubble.setBackgroundColor(npc.state.action.source === "deepseek" ? "#dbe6d2" : "#eee3cc");
      if (!initial && actor.location !== npc.state.location) this.walkActor(actor, destination.x + (index % 2) * 34 - 17, destination.y + 65);
      actor.location = npc.state.location;
    });
    const hour = world.minute / 60;
    const nightAlpha = hour >= 20 || hour < 6 ? 0.58 : hour >= 18 ? (hour - 18) * 0.24 : 0;
    this.tweens.add({ targets: this.night, alpha: nightAlpha, duration: 850 });
    this.tweens.add({ targets: this.fog, alpha: world.weather === "雾" ? 0.66 : 0, duration: 1200 });
    if (this.fire) this.fire.setAlpha(hour >= 18 || hour < 6 ? 0.65 : 0.18);
    if (this.lastAnnouncement && this.lastAnnouncement !== world.announcement && this.board) {
      this.tweens.add({ targets: this.board, scale: 1.45, angle: 3, duration: 180, yoyo: true, repeat: 2 });
    }
    this.lastAnnouncement = world.announcement;
  }

  private createActor(npc: NPC, x: number, y: number): ResidentActor {
    const key = `resident-${npc.id}`;
    if (!this.textures.exists(key)) {
      const texture = this.add.graphics();
      texture.fillStyle(Phaser.Display.Color.HexStringToColor(npc.profile.color).color, 1);
      texture.fillCircle(18, 12, 9).fillRoundedRect(8, 21, 20, 28, 8);
      texture.lineStyle(2, 0x292d27, 1).strokeCircle(18, 12, 9).strokeRoundedRect(8, 21, 20, 28, 8);
      if (npc.id === "xiaoke") texture.lineStyle(3, 0x364652, 1).lineBetween(7, 7, 29, 7);
      if (npc.id === "ajie") texture.fillStyle(0x343a37, 1).fillTriangle(5, 47, 31, 47, 18, 60);
      texture.generateTexture(key, 36, 62);
      texture.destroy();
    }
    const sprite = this.add.sprite(0, 0, key).setOrigin(0.5, 1).setScale(1.08);
    const name = this.add.text(0, 7, npc.profile.name, { fontFamily: '"PingFang SC", sans-serif', fontSize: "12px", color: "#f8f0db", stroke: "#263027", strokeThickness: 4 }).setOrigin(0.5, 0);
    const bubble = this.add.text(0, -72, this.bubbleText(npc), {
      fontFamily: '"PingFang SC", sans-serif', fontSize: "11px", color: "#2c3029", padding: { x: 8, y: 5 }, align: "center",
    }).setOrigin(0.5, 1).setBackgroundColor("#eee3cc").setAlpha(0.94);
    const container = this.add.container(x, y, [sprite, name, bubble]).setSize(94, 110).setDepth(y + 100).setInteractive({ useHandCursor: true });
    container.on("pointerover", () => this.tweens.add({ targets: container, scale: 1.08, duration: 120 }));
    container.on("pointerout", () => this.tweens.add({ targets: container, scale: 1, duration: 120 }));
    container.on("pointerdown", () => this.onResidentClick(npc.id));
    this.tweens.add({ targets: bubble, y: -77, duration: 1000 + npc.id.length * 80, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
    return { container, sprite, bubble, location: npc.state.location };
  }

  private walkActor(actor: ResidentActor, x: number, y: number) {
    this.tweens.killTweensOf(actor.container);
    const middleX = (actor.container.x + x) / 2 + (y - actor.container.y) * 0.08;
    const middleY = (actor.container.y + y) / 2;
    const bob = this.tweens.add({ targets: actor.sprite, angle: { from: -4, to: 4 }, duration: 130, yoyo: true, repeat: -1 });
    this.tweens.chain({
      targets: actor.container,
      tweens: [
        { x: middleX, y: middleY, duration: 700, ease: "Sine.easeInOut" },
        { x, y, duration: 700, ease: "Sine.easeInOut" },
      ],
      onUpdate: () => actor.container.setDepth(actor.container.y + 100),
      onComplete: () => { bob.stop(); actor.sprite.setAngle(0); },
    });
    this.tweens.add({ targets: actor.bubble, alpha: { from: 0, to: 0.94 }, duration: 500, delay: 900 });
  }

  private bubbleText(npc: NPC) {
    const reason = npc.state.action.reason.length > 25 ? `${npc.state.action.reason.slice(0, 25)}…` : npc.state.action.reason;
    return `${reason}`;
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
      type: Phaser.AUTO,
      parent: host.current,
      width: 1000,
      height: 650,
      backgroundColor: "#747961",
      scene: scene.current,
      render: { antialias: false, pixelArt: true },
      scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    });
    scene.current.setWorld(world);
    return () => { game.current?.destroy(true); game.current = undefined; };
  }, []);

  useEffect(() => { scene.current?.setWorld(world); }, [world]);
  return <div ref={host} className="town-stage" aria-label="新螈镇实时游戏场景" />;
}
