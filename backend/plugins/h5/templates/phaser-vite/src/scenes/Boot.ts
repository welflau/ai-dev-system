import Phaser from "phaser";
import { SceneKey } from "../constants";

export class Boot extends Phaser.Scene {
  constructor() {
    super({ key: SceneKey.Boot });
  }

  create(): void {
    this.scene.start(SceneKey.Game);
  }
}
