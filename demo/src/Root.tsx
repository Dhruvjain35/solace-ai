import { Composition } from "remotion";
import { Solace, SOLACE_FPS, SOLACE_DURATION } from "./Solace";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Solace"
        component={Solace}
        durationInFrames={SOLACE_DURATION}
        fps={SOLACE_FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
