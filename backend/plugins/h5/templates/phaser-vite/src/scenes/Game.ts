import Phaser from "phaser";
import { SceneKey } from "../constants";

export class Game extends Phaser.Scene {
  constructor() {
    super({ key: SceneKey.Game });
  }

  create(): void {
    this.input.removeAllListeners();
    this.add
      .text(201, 437, "{{PROJECT_TITLE}}", {
        fontSize: "28px",
        color: "#ffffff",
      })
      .setOrigin(0.5);
  }
}
