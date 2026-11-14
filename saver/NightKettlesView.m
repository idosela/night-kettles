//
//  NightKettlesView.m
//  Night Kettles: pour-over kettles, cone drippers, plunger brewers and
//  coffee grinders on the wing, with coffee cups riding their saucers and
//  beans tumbling alongside.
//
//  Every sprite is a CALayer whose contents are swapped between frames cut
//  from the PNG sheets in Resources, so the compositor does all the drawing.
//  The flight model mirrors preview/index.html; change both together.
//

#import <ScreenSaver/ScreenSaver.h>
#import <QuartzCore/QuartzCore.h>
#import <ImageIO/ImageIO.h>

// ---- Flight model (same numbers as the preview) ----

static const CGFloat kCos = 0.9396926207859084;     // the flight path climbs at 20 degrees
static const CGFloat kSin = 0.3420201433256687;
static const CGFloat kFine = 1.5;                       // sprite pixels per design unit; must match Z in art/make_sprites.py
static const CGFloat kTierSize[3] = {0.5, 0.75, 1.0};   // far, middle, near
static const CGFloat kTierPace[3] = {30, 33, 38};       // design units per second
static const NSInteger kTierOrder[20] = {0, 1, 2, 0, 1, 0, 2, 1, 0, 1, 2, 0, 1, 0, 2, 1, 0, 1, 0, 2};

// The cast, sized in design units. Everything before the cup has wings: it
// flaps, and comes in as many colourways as its sheet has rows for. Cups come
// in several accents, each in the four roasts; beans only in the four roasts.
// Every sheet is 4 frames wide; a winged row is colourway * 3 + tier, a cup's
// or a bean's is (accent * 4 + roast) * 3 + tier. The mill is the hand
// grinder, the grinder the electric one.
enum { kKettle, kDripper, kPress, kMill, kGrinder, kCup, kBean, kKindCount };
static NSString * const kKindSheet[kKindCount] = {@"kettle", @"dripper", @"press", @"mill", @"grinder", @"cup", @"bean"};
static const CGFloat kKindW[kKindCount] = {56, 56, 56, 56, 56, 40, 16};
static const CGFloat kKindH[kKindCount] = {48, 48, 48, 48, 48, 36, 16};
static const CFTimeInterval kKindTick[kKindCount] = {0.085, 0.085, 0.085, 0.085, 0.085, 0.16, 0.13};
static const NSInteger kKindOrder[20] = {0, 5, 0, 6, 3, 1, 5, 4, 6, 1, 2, 4, 6, 2, 3, 0, 5, 6, 6, 1};   // who takes each slot
static const NSInteger kFlap[6] = {0, 1, 2, 3, 2, 1};   // wing frames: up, down and back

// Steam puffs and coffee drips: puff.png and drop.png, 5 frames, row = tier.
static const CGFloat kParticleSize = 16;
static const NSInteger kParticleFrames = 5;
static const CFTimeInterval kParticleTick = 0.17;
static const CGFloat kSpoutX = 53, kSpoutY = 22;        // the kettle's gooseneck tip, in its sprite
static const CGFloat kDripX = 30, kDripY = 38;          // the underside of the dripper, in its sprite

static const CGFloat kStarPace[2] = {1.0, 2.2};         // design units per second, per star layer
static const uint32_t kStarTones[2][3] = {{0x2c3154, 0x3c4370, 0x3c4370}, {0x59618f, 0x8d97c4, 0xdfe5ff}};

static NSString * const kFlockKey = @"Flock";   // 0.4 ... 2.0, times the usual number aloft
static NSString * const kSpeedKey = @"Speed";   // 0.5 ... 2.0
static NSString * const kRoastKey = @"Roast";   // 0 ... 3, light to French

static CGFloat NKRand(CGFloat lo, CGFloat hi) {
    return lo + (hi - lo) * (arc4random_uniform(1 << 24) / (CGFloat)(1 << 24));
}

static CGFloat NKWrap(CGFloat value, CGFloat size) {
    CGFloat r = fmod(value, size);
    return r < 0 ? r + size : r;
}

static NSColor *NKColor(uint32_t hex) {
    return [NSColor colorWithSRGBRed:((hex >> 16) & 0xff) / 255.0
                               green:((hex >> 8) & 0xff) / 255.0
                                blue:(hex & 0xff) / 255.0
                               alpha:1];
}

// Points per design unit for each tier. Each sprite pixel gets a whole number
// of device pixels once the screen is big enough, so the pixel art stays crisp.
static BOOL NKTierScales(CGFloat width, CGFloat height, CGFloat dpr, CGFloat scale[3]) {
    CGFloat near = MIN(width, height * 2) * dpr / (400 * kFine);   // device pixels per sprite pixel
    BOOL crisp = near >= 2.5;
    CGFloat sizes[3];
    for (int tier = 0; tier < 3; tier++) {
        sizes[tier] = crisp ? round(round(near) * kTierSize[tier]) : near * kTierSize[tier];
    }
    if (crisp && sizes[0] >= sizes[1]) sizes[0] = sizes[1] - 1;    // keep the far tier smaller than the middle one
    for (int tier = 0; tier < 3; tier++) {
        scale[tier] = sizes[tier] * kFine / dpr;
    }
    return crisp;
}

static NSInteger NKFlockSize(double flock, CGFloat width, CGFloat height, CGFloat nearScale) {
    return MAX(3, lround(flock * width * height / (nearScale * nearScale * 6200)));
}

// Cuts a sprite sheet into rows of frames, each a CGImage. The cell size is
// given in design units.
static NSArray<NSArray *> *NKLoadSheet(NSBundle *bundle, NSString *name, CGFloat width, CGFloat height) {
    size_t cellW = (size_t)lround(width * kFine), cellH = (size_t)lround(height * kFine);
    NSMutableArray<NSArray *> *rows = [NSMutableArray array];
    NSURL *url = [bundle URLForResource:name withExtension:@"png"];
    CGImageSourceRef source = url ? CGImageSourceCreateWithURL((__bridge CFURLRef)url, NULL) : NULL;
    CGImageRef sheet = source ? CGImageSourceCreateImageAtIndex(source, 0, NULL) : NULL;
    if (source) CFRelease(source);
    if (!sheet) {
        NSLog(@"Night Kettles: could not load %@.png", name);
        return rows;
    }
    for (size_t y = 0; y + cellH <= CGImageGetHeight(sheet); y += cellH) {
        NSMutableArray *row = [NSMutableArray array];
        for (size_t x = 0; x + cellW <= CGImageGetWidth(sheet); x += cellW) {
            CGImageRef cell = CGImageCreateWithImageInRect(sheet, CGRectMake(x, y, cellW, cellH));
            if (cell) {
                [row addObject:(__bridge id)cell];
                CGImageRelease(cell);
            }
        }
        [rows addObject:row];
    }
    CGImageRelease(sheet);
    return rows;
}

static id NKCell(NSArray<NSArray *> *sheet, NSInteger row, NSInteger frame) {
    if (row < 0 || row >= (NSInteger)sheet.count) return nil;
    NSArray *cells = sheet[row];
    return frame >= 0 && frame < (NSInteger)cells.count ? cells[frame] : nil;
}

// ---- The cast ----

// A flyer's place is (along, across): distance along the flight path and
// across it, measured from the middle of the screen.
@interface NKFlyer : NSObject
@property (nonatomic, strong) CALayer *layer;
@property (nonatomic) NSInteger kind, tier, variant, frame, burst;
@property (nonatomic) CGFloat along, across, leaveAt, speed;
@property (nonatomic) CFTimeInterval clock, emitIn;
@end
@implementation NKFlyer
@end

@interface NKParticle : NSObject
@property (nonatomic, strong) CALayer *layer;
@property (nonatomic) BOOL alive, drop;         // a drip of coffee, otherwise a puff of steam
@property (nonatomic) NSInteger tier, frame;
@property (nonatomic) CGFloat x, y, vx, vy, ay;
@property (nonatomic) CFTimeInterval age;
@end
@implementation NKParticle
@end

@interface NKStar : NSObject
@property (nonatomic, strong) CALayer *layer;
@property (nonatomic) NSInteger level;
@property (nonatomic) CGFloat x, y;
@end
@implementation NKStar
@end

// ---- The saver ----

@interface NightKettlesView : ScreenSaverView
@end

@implementation NightKettlesView {
    NSArray<NSArray<NSArray *> *> *_sheets;     // per kind, as [row][frame]
    NSArray<NSArray *> *_steam, *_drips;
    NSMutableArray<NKFlyer *> *_flyers;
    NSMutableArray<NKParticle *> *_particles;
    NSMutableArray<NKStar *> *_stars;

    BOOL _stale;            // the view changed: lay the scene out again before the next frame
    BOOL _crisp;
    CFTimeInterval _last;
    CGFloat _W, _H, _dpr;
    CGFloat _scale[3];      // points per design unit, per tier
    CGFloat _crossHalf;     // half the screen's extent across the flight path
    CGFloat _starDrift[2];
    long _starDX[2], _starDY[2];

    double _flock, _speed;  // the three options
    NSInteger _roast;

    NSWindow *_sheet;
    NSSlider *_flockSlider, *_speedSlider, *_roastSlider;
    NSTextField *_flockValue, *_speedValue, *_roastValue;
}

// The isPreview flag has been unreliable ever since savers moved into the
// legacyScreenSaver host, so the System Settings thumbnail is told apart by size.
static BOOL NKIsThumbnail(NSSize size) {
    return !(size.width > 400 && size.height > 300);
}

- (instancetype)initWithFrame:(NSRect)frame isPreview:(BOOL)isPreview {
    self = [super initWithFrame:frame isPreview:NKIsThumbnail(frame.size)];
    if (self) {
        self.animationTimeInterval = 1.0 / 60.0;

        // A layer-hosting view: we own the layer tree.
        CALayer *root = [CALayer layer];
        root.backgroundColor = NKColor(0x04050e).CGColor;
        root.masksToBounds = YES;
        self.layer = root;
        self.wantsLayer = YES;

        NSBundle *bundle = [NSBundle bundleForClass:[self class]];
        NSMutableArray<NSArray<NSArray *> *> *sheets = [NSMutableArray array];
        for (int kind = 0; kind < kKindCount; kind++) {
            [sheets addObject:NKLoadSheet(bundle, kKindSheet[kind], kKindW[kind], kKindH[kind])];
        }
        _sheets = sheets;
        _steam = NKLoadSheet(bundle, @"puff", kParticleSize, kParticleSize);
        _drips = NKLoadSheet(bundle, @"drop", kParticleSize, kParticleSize);
        _flyers = [NSMutableArray array];
        _particles = [NSMutableArray array];
        _stars = [NSMutableArray array];
        _stale = YES;

        [[NSDistributedNotificationCenter defaultCenter] addObserver:self
                                                            selector:@selector(saverWillStop:)
                                                                name:@"com.apple.screensaver.willstop"
                                                              object:nil];
    }
    return self;
}

- (void)dealloc {
    [[NSDistributedNotificationCenter defaultCenter] removeObserver:self];
}

// Since macOS 14 the system no longer calls stopAnimation or tears the view
// down when the saver is dismissed; each showing would leave another copy
// animating in the background. Leaving the host process is the usual remedy.
- (void)saverWillStop:(NSNotification *)notification {
    if (NKIsThumbnail(self.bounds.size)) return;
    if (@available(macOS 14.0, *)) {
        exit(0);
    }
}

- (void)startAnimation {
    [super startAnimation];
    _stale = YES;
    _last = 0;
}

- (void)setFrameSize:(NSSize)size {
    [super setFrameSize:size];
    _stale = YES;
}

- (void)viewDidChangeBackingProperties {
    [super viewDidChangeBackingProperties];
    _stale = YES;
}

- (void)animateOneFrame {
    CFTimeInterval now = CACurrentMediaTime();
    CFTimeInterval dt = _last > 0 ? MIN(0.05, now - _last) : 0;
    _last = now;

    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    if (_stale) {
        _stale = NO;
        [self layoutScene];
    }
    [self step:dt];
    [self render];
    [CATransaction commit];
}

// ---- Options ----

- (ScreenSaverDefaults *)options {
    NSString *module = [[NSBundle bundleForClass:[self class]] bundleIdentifier] ?: @"local.NightKettles";
    ScreenSaverDefaults *defaults = [ScreenSaverDefaults defaultsForModuleWithName:module];
    [defaults registerDefaults:@{kFlockKey: @1.0, kSpeedKey: @1.0, kRoastKey: @1}];
    return defaults;
}

- (void)readOptions {
    ScreenSaverDefaults *defaults = [self options];
    [defaults synchronize];
    _flock = MAX(0.4, MIN(2.0, [defaults doubleForKey:kFlockKey]));
    _speed = MAX(0.5, MIN(2.0, [defaults doubleForKey:kSpeedKey]));
    _roast = MAX(0, MIN(3, [defaults integerForKey:kRoastKey]));
}

// ---- Scene ----

- (void)layoutScene {
    [self readOptions];

    CALayer *root = self.layer;
    _W = NSWidth(self.bounds);
    _H = NSHeight(self.bounds);
    _dpr = self.window ? self.window.backingScaleFactor : NSScreen.mainScreen.backingScaleFactor;
    if (_dpr <= 0) _dpr = 1;
    _crisp = NKTierScales(_W, _H, _dpr, _scale);
    _crossHalf = (_W * kSin + _H * kCos) / 2;

    root.sublayers = nil;
    [_flyers removeAllObjects];
    [_particles removeAllObjects];
    [_stars removeAllObjects];
    if (_W < 1 || _H < 1) return;

    CAGradientLayer *sky = [CAGradientLayer layer];
    sky.frame = CGRectMake(0, 0, _W, _H);
    sky.colors = @[(__bridge id)NKColor(0x0b0e26).CGColor, (__bridge id)NKColor(0x04050e).CGColor];
    sky.startPoint = CGPointMake(0.5, 1);   // layers are y-up: 1 is the top
    sky.endPoint = CGPointMake(0.5, 0);
    sky.zPosition = -10;
    [root addSublayer:sky];

    [self seedStars];

    NSInteger count = NKFlockSize(_flock, _W, _H, _scale[2]);
    for (NSInteger i = 0; i < count; i++) {
        NKFlyer *f = [NKFlyer new];
        f.tier = kTierOrder[i % 20];
        f.kind = kKindOrder[i % 20];
        f.layer = [self spriteLayerOfWidth:kKindW[f.kind] height:kKindH[f.kind] tier:f.tier z:f.tier + 0.5];
        [self launch:f scatter:YES];
        [_flyers addObject:f];
    }
}

- (CALayer *)spriteLayerOfWidth:(CGFloat)width height:(CGFloat)height tier:(NSInteger)tier z:(CGFloat)z {
    CALayer *layer = [CALayer layer];
    layer.anchorPoint = CGPointZero;
    layer.bounds = CGRectMake(0, 0, width * _scale[tier], height * _scale[tier]);
    layer.magnificationFilter = _crisp ? kCAFilterNearest : kCAFilterLinear;
    layer.zPosition = z;
    [self.layer addSublayer:layer];
    return layer;
}

- (void)seedStars {
    CGFloat unit = MAX(1.0, round(_scale[2] * _dpr / 4)) / _dpr;   // one star pixel, in points
    NSInteger count = MIN(400, MAX(20, lround(_W * _H / (_scale[2] * _scale[2] * 520))));
    for (NSInteger i = 0; i < count; i++) {
        NKStar *star = [NKStar new];
        star.level = NKRand(0, 1) < 0.6 ? 0 : 1;
        star.x = round(NKRand(0, _W) * _dpr) / _dpr;
        star.y = round(NKRand(0, _H) * _dpr) / _dpr;
        CGFloat bright = NKRand(0, 1);
        NSInteger tones = star.level == 0 ? 2 : 3;
        NSInteger tone = MIN(tones - 1, (NSInteger)floor(bright * bright * tones));
        CGFloat size = unit * (star.level == 1 && bright > 0.8 ? 2 : 1);

        CALayer *layer = [CALayer layer];
        layer.anchorPoint = CGPointZero;
        layer.bounds = CGRectMake(0, 0, size, size);
        layer.backgroundColor = NKColor(kStarTones[star.level][tone]).CGColor;
        layer.zPosition = -5;
        [self.layer addSublayer:layer];
        star.layer = layer;
        [_stars addObject:star];
    }
    _starDrift[0] = _starDrift[1] = 0;
    _starDX[0] = _starDX[1] = LONG_MIN;   // forces the first placement
    _starDY[0] = _starDY[1] = LONG_MIN;
}

// Send a flyer in from the upwind edge, or (scatter) drop it anywhere along
// its lane. Of a few random lanes, it takes the one with the most room.
- (void)launch:(NKFlyer *)f scatter:(BOOL)scatter {
    CGFloat s = _scale[f.tier];
    NSUInteger rowsPerLook = f.kind < kCup ? 3 : 12;   // 3 tiers, times 4 roasts for cups and beans
    f.variant = arc4random_uniform((uint32_t)MAX(1, _sheets[f.kind].count / rowsPerLook));   // a colourway, or a cup's accent
    f.speed = kTierPace[f.tier] * s * NKRand(0.92, 1.08);
    f.clock = NKRand(0, 10);
    f.burst = 2 + arc4random_uniform(2);
    f.emitIn = NKRand(0.4, 3.4);
    f.frame = -1;                                   // redraw: the colourway may have changed

    CGFloat margin = kKindW[f.kind] * s * 0.6;
    CGFloat bestGap = -1;
    for (int i = 0; i < 6; i++) {
        // The stretch of this lane for which a sprite is at least partly on screen.
        CGFloat across = NKRand(-_crossHalf, _crossHalf);
        CGFloat from = MAX((-_W / 2 - margin - across * kSin) / kCos, (across * kCos - _H / 2 - margin) / kSin);
        CGFloat to = MIN((_W / 2 + margin - across * kSin) / kCos, (across * kCos + _H / 2 + margin) / kSin);
        CGFloat along = scatter ? NKRand(from, to) : from;
        CGFloat gap = CGFLOAT_MAX;
        for (NKFlyer *other in _flyers) {
            if (other != f) gap = MIN(gap, hypot(other.along - along, other.across - across));
        }
        if (gap > bestGap) {
            bestGap = gap;
            f.along = along;
            f.across = across;
            f.leaveAt = to;
        }
    }
}

// Where a flyer's sprite is centred, in points with y running down as in the
// preview. Anything with wings sinks as they come up and rises on the
// downstroke; saucers hover; beans just tumble.
- (CGPoint)centreOf:(NKFlyer *)f {
    CGFloat s = _scale[f.tier];
    CGFloat bob = 0;
    if (f.kind < kCup) {
        bob = cos(f.clock / (6 * kKindTick[f.kind]) * 2 * M_PI) * 1.5 * s;
    } else if (f.kind == kCup) {
        bob = sin(f.clock / 2.6 * 2 * M_PI) * 2 * s;
    }
    return CGPointMake(_W / 2 + f.along * kCos + f.across * kSin,
                       _H / 2 - f.along * kSin + f.across * kCos + bob);
}

// A puff of steam from the kettle's spout, or a drip from under the dripper.
// Steam falls behind and lifts clear of the kettle; a drip keeps most of the
// dripper's speed and falls away.
- (void)emitFrom:(NKFlyer *)f drop:(BOOL)drop {
    NKParticle *particle = nil;
    for (NKParticle *spare in _particles) {
        if (!spare.alive && spare.tier == f.tier) {
            particle = spare;
            break;
        }
    }
    if (!particle) {
        particle = [NKParticle new];
        particle.tier = f.tier;
        particle.layer = [self spriteLayerOfWidth:kParticleSize height:kParticleSize tier:f.tier z:f.tier];
        [_particles addObject:particle];
    }

    CGFloat s = _scale[f.tier];
    CGPoint centre = [self centreOf:f];
    CGFloat v = f.speed * _speed;
    particle.alive = YES;
    particle.drop = drop;
    particle.age = 0;
    particle.frame = -1;
    if (drop) {
        particle.x = centre.x + (kDripX - 28) * s;
        particle.y = centre.y + (kDripY - 24 + 3) * s;
        particle.vx = v * kCos * 0.7;
        particle.vy = -v * kSin * 0.7;
        particle.ay = 60 * s;
    } else {
        particle.x = centre.x + (kSpoutX - 28 + 3) * s;
        particle.y = centre.y + (kSpoutY - 24 - 4) * s;
        particle.vx = v * (kCos - 0.42);
        particle.vy = -v * (kSin + 0.34);
        particle.ay = 0;
    }
    particle.layer.hidden = NO;
}

- (void)step:(CFTimeInterval)dt {
    for (int level = 0; level < 2; level++) {
        _starDrift[level] += kStarPace[level] * _scale[2] * _speed * dt;
    }

    for (NKFlyer *f in _flyers) {
        f.along += f.speed * _speed * dt;
        f.clock += dt;
        if (f.along > f.leaveAt) [self launch:f scatter:NO];
        if (f.kind != kKettle && f.kind != kDripper) continue;
        f.emitIn -= dt;
        if (f.emitIn > 0) continue;
        if (f.kind == kDripper) {
            [self emitFrom:f drop:YES];
            f.emitIn = NKRand(0.7, 1.5);
        } else {                        // the kettle whistles: two or three quick puffs, then a rest
            [self emitFrom:f drop:NO];
            f.burst -= 1;
            if (f.burst > 0) {
                f.emitIn = 0.26;
            } else {
                f.burst = 2 + arc4random_uniform(2);
                f.emitIn = NKRand(2, 4.5);
            }
        }
    }

    for (NKParticle *particle in _particles) {
        if (!particle.alive) continue;
        particle.age += dt;
        particle.vy += particle.ay * dt;
        particle.x += particle.vx * dt;
        particle.y += particle.vy * dt;
        if (particle.age >= kParticleFrames * kParticleTick) {
            particle.alive = NO;
            particle.layer.hidden = YES;
        }
    }
}

// Puts a sprite layer's centre at a point given in y-down coordinates,
// snapped to device pixels.
- (void)place:(CALayer *)layer at:(CGPoint)centre {
    CGSize size = layer.bounds.size;
    layer.position = CGPointMake(round((centre.x - size.width / 2) * _dpr) / _dpr,
                                 round((_H - centre.y - size.height / 2) * _dpr) / _dpr);
}

- (void)render {
    for (NKFlyer *f in _flyers) {
        BOOL winged = f.kind < kCup;
        NSInteger tick = (NSInteger)floor(f.clock / kKindTick[f.kind]);
        NSInteger frame = winged ? kFlap[tick % 6] : tick % 4;
        if (frame != f.frame) {
            f.frame = frame;
            f.layer.contents = NKCell(_sheets[f.kind], (winged ? f.variant : f.variant * 4 + _roast) * 3 + f.tier, frame);
        }
        [self place:f.layer at:[self centreOf:f]];
    }

    for (NKParticle *particle in _particles) {
        if (!particle.alive) continue;
        NSInteger frame = MIN(kParticleFrames - 1, (NSInteger)floor(particle.age / kParticleTick));
        if (frame != particle.frame) {
            particle.frame = frame;
            particle.layer.contents = NKCell(particle.drop ? _drips : _steam, particle.tier, frame);
        }
        [self place:particle.layer at:CGPointMake(particle.x, particle.y)];
    }

    // Stars drift the other way, a whole device pixel at a time, so most
    // frames leave them alone.
    BOOL moved[2];
    for (int level = 0; level < 2; level++) {
        long dx = lround(_starDrift[level] * kCos * _dpr);
        long dy = lround(_starDrift[level] * kSin * _dpr);
        moved[level] = dx != _starDX[level] || dy != _starDY[level];
        _starDX[level] = dx;
        _starDY[level] = dy;
    }
    for (NKStar *star in _stars) {
        if (!moved[star.level]) continue;
        CGFloat x = NKWrap(star.x - _starDX[star.level] / _dpr, _W);
        CGFloat y = NKWrap(star.y + _starDY[star.level] / _dpr, _H);
        star.layer.position = CGPointMake(x, _H - y - star.layer.bounds.size.height);
    }
}

// ---- Options sheet ----

- (BOOL)hasConfigureSheet {
    return YES;
}

- (NSWindow *)configureSheet {
    if (!_sheet) {
        _sheet = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 420, 212)
                                             styleMask:NSWindowStyleMaskTitled
                                               backing:NSBackingStoreBuffered
                                                 defer:YES];
        NSView *content = _sheet.contentView;

        NSTextField *title = [NSTextField labelWithString:@"Night Kettles"];
        title.font = [NSFont boldSystemFontOfSize:15];
        title.frame = NSMakeRect(20, 172, 380, 20);
        [content addSubview:title];

        _flockSlider = [self sliderNamed:@"Flock" atY:130 from:0.4 to:2.0 in:content];
        _speedSlider = [self sliderNamed:@"Speed" atY:98 from:0.5 to:2.0 in:content];
        _roastSlider = [self sliderNamed:@"Roast" atY:66 from:0 to:3 in:content];
        _roastSlider.numberOfTickMarks = 4;
        _roastSlider.allowsTickMarkValuesOnly = YES;
        _flockValue = [self valueLabelAtY:130 in:content];
        _speedValue = [self valueLabelAtY:98 in:content];
        _roastValue = [self valueLabelAtY:66 in:content];

        NSButton *cancel = [NSButton buttonWithTitle:@"Cancel" target:self action:@selector(closeSheet:)];
        cancel.frame = NSMakeRect(232, 14, 84, 32);
        cancel.keyEquivalent = @"\033";
        [content addSubview:cancel];

        NSButton *ok = [NSButton buttonWithTitle:@"OK" target:self action:@selector(closeSheet:)];
        ok.frame = NSMakeRect(316, 14, 84, 32);
        ok.keyEquivalent = @"\r";
        ok.tag = 1;
        [content addSubview:ok];
    }

    [self readOptions];
    _flockSlider.doubleValue = _flock;
    _speedSlider.doubleValue = _speed;
    _roastSlider.integerValue = _roast;
    [self optionChanged:nil];
    return _sheet;
}

- (NSSlider *)sliderNamed:(NSString *)name atY:(CGFloat)y from:(double)min to:(double)max in:(NSView *)content {
    NSTextField *label = [NSTextField labelWithString:name];
    label.frame = NSMakeRect(20, y, 70, 18);
    [content addSubview:label];

    NSSlider *slider = [NSSlider sliderWithValue:min minValue:min maxValue:max target:self action:@selector(optionChanged:)];
    slider.frame = NSMakeRect(96, y - 3, 196, 24);
    [content addSubview:slider];
    return slider;
}

- (NSTextField *)valueLabelAtY:(CGFloat)y in:(NSView *)content {
    NSTextField *value = [NSTextField labelWithString:@""];
    value.frame = NSMakeRect(304, y, 96, 18);
    [content addSubview:value];
    return value;
}

- (void)optionChanged:(id)sender {
    double flock = round(_flockSlider.doubleValue * 10) / 10;
    NSScreen *screen = NSScreen.mainScreen;
    if (screen) {
        CGFloat scale[3];
        NKTierScales(NSWidth(screen.frame), NSHeight(screen.frame), screen.backingScaleFactor, scale);
        NSInteger count = NKFlockSize(flock, NSWidth(screen.frame), NSHeight(screen.frame), scale[2]);
        _flockValue.stringValue = [NSString stringWithFormat:@"%ld aloft", (long)count];
    } else {
        _flockValue.stringValue = [NSString stringWithFormat:@"%.1f×", flock];
    }
    _speedValue.stringValue = [NSString stringWithFormat:@"%.1f×", round(_speedSlider.doubleValue * 10) / 10];
    NSArray<NSString *> *roasts = @[@"Light", @"Medium", @"Dark", @"French"];
    _roastValue.stringValue = roasts[MAX(0, MIN(3, _roastSlider.integerValue))];
}

- (void)closeSheet:(NSButton *)sender {
    if (sender.tag == 1) {
        ScreenSaverDefaults *defaults = [self options];
        [defaults setDouble:round(_flockSlider.doubleValue * 10) / 10 forKey:kFlockKey];
        [defaults setDouble:round(_speedSlider.doubleValue * 10) / 10 forKey:kSpeedKey];
        [defaults setInteger:_roastSlider.integerValue forKey:kRoastKey];
        [defaults synchronize];
        _stale = YES;   // the thumbnail picks the new options up straight away
    }

    NSWindow *parent = _sheet.sheetParent;
    if (parent) {
        [parent endSheet:_sheet];
    } else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        [NSApp endSheet:_sheet];
#pragma clang diagnostic pop
    }
}

@end
