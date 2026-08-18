(function initializeCosmicBackground() {
    const canvas = document.getElementById("starCanvas");
    const background = document.querySelector(".cosmic-background");
    const saturn = document.getElementById("saturnScene");
    const nebulas = Array.from(document.querySelectorAll(".nebula"));

    if (!canvas || !background || !saturn) return;

    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const starColors = [
        [255, 255, 255],
        [216, 180, 254],
        [192, 132, 252],
        [147, 197, 253],
        [167, 139, 250]
    ];

    let stars = [];
    let viewportWidth = 0;
    let viewportHeight = 0;
    let pixelRatio = 1;
    let animationFrame = null;
    let resizeFrame = null;
    let previousTime = 0;
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;

    function createStars() {
        // Density is intentionally capped to keep integrated laptop graphics smooth.
        const starCount = Math.max(
            90,
            Math.min(240, Math.round((viewportWidth * viewportHeight) / 6500))
        );

        stars = Array.from({ length: starCount }, () => ({
            x: Math.random() * viewportWidth,
            y: Math.random() * viewportHeight,
            radius: Math.random() < 0.86
                ? 0.35 + Math.random() * 0.75
                : 1.1 + Math.random() * 1.25,
            opacity: 0.2 + Math.random() * 0.68,
            twinkle: 0.0007 + Math.random() * 0.0015,
            phase: Math.random() * Math.PI * 2,
            driftX: 0.001 + Math.random() * 0.003,
            driftY: 0.0004 + Math.random() * 0.0017,
            color: starColors[Math.floor(Math.random() * starColors.length)]
        }));
    }

    function resizeCanvas() {
        viewportWidth = window.innerWidth;
        viewportHeight = window.innerHeight;
        pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);

        canvas.width = Math.round(viewportWidth * pixelRatio);
        canvas.height = Math.round(viewportHeight * pixelRatio);
        canvas.style.width = `${viewportWidth}px`;
        canvas.style.height = `${viewportHeight}px`;
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        createStars();

        if (reducedMotionQuery.matches) drawStars(0, 0);
    }

    function applyParallax() {
        currentX += (targetX - currentX) * 0.045;
        currentY += (targetY - currentY) * 0.045;

        saturn.style.setProperty("--parallax-x", `${currentX * -22}px`);
        saturn.style.setProperty("--parallax-y", `${currentY * -15}px`);

        const strengths = [10, -7, 5];
        nebulas.forEach((nebula, index) => {
            const strength = strengths[index] || 5;
            nebula.style.setProperty("--parallax-x", `${currentX * strength}px`);
            nebula.style.setProperty("--parallax-y", `${currentY * strength * 0.65}px`);
        });
    }

    function drawStars(time, delta) {
        context.clearRect(0, 0, viewportWidth, viewportHeight);
        const starShiftX = currentX * 5;
        const starShiftY = currentY * 3;
        const shouldMove = !reducedMotionQuery.matches;

        for (const star of stars) {
            if (shouldMove) {
                star.x += star.driftX * delta;
                star.y += star.driftY * delta;

                if (star.x > viewportWidth + 3) star.x = -3;
                if (star.y > viewportHeight + 3) star.y = -3;
            }

            const pulse = shouldMove
                ? 0.72 + Math.sin(time * star.twinkle + star.phase) * 0.28
                : 0.88;
            const alpha = Math.max(0.08, star.opacity * pulse);
            const [red, green, blue] = star.color;

            context.beginPath();
            context.arc(
                star.x + starShiftX,
                star.y + starShiftY,
                star.radius,
                0,
                Math.PI * 2
            );
            context.fillStyle = `rgba(${red}, ${green}, ${blue}, ${alpha})`;
            context.fill();

            if (star.radius > 1.65) {
                context.beginPath();
                context.arc(
                    star.x + starShiftX,
                    star.y + starShiftY,
                    star.radius * 3.2,
                    0,
                    Math.PI * 2
                );
                context.fillStyle = `rgba(${red}, ${green}, ${blue}, ${alpha * 0.08})`;
                context.fill();
            }
        }
    }

    function render(time) {
        const delta = Math.min(34, previousTime ? time - previousTime : 16);
        previousTime = time;
        applyParallax();
        drawStars(time, delta);

        if (!reducedMotionQuery.matches && !document.hidden) {
            animationFrame = window.requestAnimationFrame(render);
        }
    }

    function startAnimation() {
        if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
        animationFrame = null;
        previousTime = 0;

        if (reducedMotionQuery.matches) {
            targetX = 0;
            targetY = 0;
            currentX = 0;
            currentY = 0;
            applyParallax();
            drawStars(0, 0);
            return;
        }

        animationFrame = window.requestAnimationFrame(render);
    }

    function handlePointerMove(event) {
        if (reducedMotionQuery.matches) return;
        targetX = (event.clientX / viewportWidth - 0.5) * 2;
        targetY = (event.clientY / viewportHeight - 0.5) * 2;
    }

    function resetPointer() {
        targetX = 0;
        targetY = 0;
    }

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", resetPointer, { passive: true });
    window.addEventListener("blur", resetPointer);
    window.addEventListener("resize", () => {
        if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
        resizeFrame = window.requestAnimationFrame(() => {
            resizeFrame = null;
            resizeCanvas();
        });
    }, { passive: true });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden && animationFrame !== null) {
            window.cancelAnimationFrame(animationFrame);
            animationFrame = null;
        } else if (!document.hidden) {
            startAnimation();
        }
    });

    if (typeof reducedMotionQuery.addEventListener === "function") {
        reducedMotionQuery.addEventListener("change", startAnimation);
    } else {
        reducedMotionQuery.addListener(startAnimation);
    }

    resizeCanvas();
    startAnimation();
}());
