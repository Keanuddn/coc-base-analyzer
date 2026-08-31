import Foundation

/// Der konkrete Plan, auf den die App zugeschnitten ist.
///
/// Zwei Festlegungen aus dem Plan sind hier bewusst umgesetzt:
///
/// 1. **Cable Flies stehen zwischen den beiden Isolations-Trizeps-Übungen**,
///    also nach den Overhead Extensions und vor den Pushdowns. Die
///    Positionsangabe hat Vorrang vor der Aufzählungsreihenfolge.
/// 2. **Warm-ups stehen direkt vor der zugehörigen Arbeitsübung**, nicht alle
///    am Tagesanfang. Sonst läge das RDL-Warm-up weit vor den RDLs.
public enum DefaultPlan {
    public static let versionID = "ppl-3-tage-v1"

    // MARK: - Übungen

    public enum ID {
        public static let inclinePress = "incline-chest-press"
        public static let flatPress = "flat-bench-machine-press"
        public static let dips = "dips-triceps"
        public static let overheadExtension = "overhead-tricep-extension"
        public static let cableFly = "cable-fly"
        public static let pushdown = "tricep-pushdown"

        public static let pullUp = "pull-up"
        public static let closeRow = "close-grip-row"
        public static let latPulldown = "lat-pulldown"
        public static let reversePecDeck = "reverse-pec-deck"
        public static let bicepCurl = "bicep-curl"
        public static let wristCurl = "wrist-curl"
        public static let hammerCurl = "hammer-curl"

        public static let legPress = "leg-press"
        public static let romanianDeadlift = "romanian-deadlift"
        public static let calfRaise = "calf-raise"
        public static let lateralRaise = "lateral-raise"
        public static let shrug = "shrug"
        public static let shoulderPress = "shoulder-press-machine"
    }

    public static let exercises: [Exercise] = [
        Exercise(
            id: ID.inclinePress,
            name: "Incline Chest Press",
            muscleGroups: [.chest, .triceps, .shoulders],
            role: .compound,
            loadKind: .machine
        ),
        Exercise(
            id: ID.flatPress,
            name: "Flat Bench / Machine Press",
            muscleGroups: [.chest, .triceps],
            role: .compound,
            loadKind: .machine,
            knownAlternatives: [ID.inclinePress]
        ),
        Exercise(
            id: ID.dips,
            name: "Dips (Trizeps-Fokus)",
            muscleGroups: [.triceps, .chest],
            role: .compound,
            loadKind: .bodyweight
        ),
        Exercise(
            id: ID.overheadExtension,
            name: "Overhead Tricep Extensions",
            muscleGroups: [.triceps],
            role: .isolation,
            loadKind: .cable,
            knownAlternatives: [ID.pushdown]
        ),
        Exercise(
            id: ID.cableFly,
            name: "Cable Flies",
            muscleGroups: [.chest],
            role: .isolation,
            loadKind: .cable
        ),
        Exercise(
            id: ID.pushdown,
            name: "Tricep Pushdowns (cross-cable)",
            muscleGroups: [.triceps],
            role: .isolation,
            loadKind: .cable,
            knownAlternatives: [ID.overheadExtension]
        ),

        Exercise(
            id: ID.pullUp,
            name: "Pull-ups",
            muscleGroups: [.back, .biceps],
            role: .compound,
            loadKind: .bodyweight
        ),
        Exercise(
            id: ID.closeRow,
            name: "Enges Rudern",
            muscleGroups: [.back, .biceps],
            role: .compound,
            loadKind: .cable
        ),
        Exercise(
            id: ID.latPulldown,
            name: "Lat Pulldowns",
            muscleGroups: [.back, .biceps],
            role: .compound,
            loadKind: .cable,
            knownAlternatives: [ID.pullUp]
        ),
        Exercise(
            id: ID.reversePecDeck,
            name: "Reverse Pec Deck Flys",
            muscleGroups: [.back, .shoulders],
            role: .isolation,
            loadKind: .machine
        ),
        Exercise(
            id: ID.bicepCurl,
            name: "Bizeps Curls",
            muscleGroups: [.biceps],
            role: .isolation,
            loadKind: .dumbbell,
            weightStep: WeightStep(kilograms: 2)
        ),
        Exercise(
            id: ID.wristCurl,
            name: "Wrist Curls",
            muscleGroups: [.forearms],
            role: .isolation,
            loadKind: .dumbbell,
            weightStep: WeightStep(kilograms: 2)
        ),
        Exercise(
            id: ID.hammerCurl,
            name: "Hammercurls",
            muscleGroups: [.biceps, .forearms],
            role: .isolation,
            loadKind: .dumbbell,
            weightStep: WeightStep(kilograms: 2),
            knownAlternatives: [ID.bicepCurl]
        ),

        Exercise(
            id: ID.legPress,
            name: "Leg Press",
            muscleGroups: [.quads, .glutes],
            role: .compound,
            loadKind: .machine
        ),
        Exercise(
            id: ID.romanianDeadlift,
            name: "Romanian Deadlifts",
            muscleGroups: [.hamstrings, .glutes, .back],
            role: .compound,
            loadKind: .barbell
        ),
        Exercise(
            id: ID.calfRaise,
            name: "Wadenheben",
            muscleGroups: [.calves],
            role: .isolation,
            loadKind: .machine
        ),
        Exercise(
            id: ID.lateralRaise,
            name: "Lateral Raises",
            muscleGroups: [.shoulders],
            role: .isolation,
            loadKind: .dumbbell,
            weightStep: WeightStep(kilograms: 2)
        ),
        Exercise(
            id: ID.shrug,
            name: "Shrugs",
            muscleGroups: [.traps],
            role: .isolation,
            loadKind: .dumbbell,
            weightStep: WeightStep(kilograms: 2)
        ),
        Exercise(
            id: ID.shoulderPress,
            name: "Shoulder Press Machine",
            muscleGroups: [.shoulders, .triceps],
            role: .compound,
            loadKind: .machine
        )
    ]

    // MARK: - Push

    static let pushDay = DayTemplate(day: .push, blocks: [
        .single(id: "push-1-incline", exerciseID: ID.inclinePress, sets: [
            .warmup(reps: .range(min: 10, max: 12), note: "leer / leicht"),
            .warmup(reps: .range(min: 6, max: 8), note: "~50 %"),
            .warmup(reps: .range(min: 3, max: 4), note: "~75–80 %"),
            .work(reps: .range(min: 6, max: 10), pause: .range(min: 120, max: 150)),
            .work(reps: .range(min: 6, max: 10), pause: .range(min: 120, max: 150)),
            .work(reps: .range(min: 6, max: 10), pause: .range(min: 120, max: 150)),
            .work(reps: .range(min: 6, max: 10), pause: .range(min: 120, max: 150))
        ]),
        .single(id: "push-2-flat", exerciseID: ID.flatPress, sets: [
            .work(reps: .range(min: 6, max: 10), pause: .seconds(120)),
            .work(reps: .range(min: 6, max: 10), pause: .seconds(120)),
            .work(reps: .range(min: 6, max: 10), pause: .seconds(120))
        ]),
        .single(id: "push-3-dips", exerciseID: ID.dips, sets: [
            .work(reps: .range(min: 8, max: 12), pause: .seconds(90)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(90)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(90))
        ]),
        .single(id: "push-4-overhead", exerciseID: ID.overheadExtension, sets: [
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75)),
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75)),
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75))
        ]),
        // Position laut Plan: zwischen den beiden Isolations-Trizeps-Übungen.
        .single(id: "push-5-flies", exerciseID: ID.cableFly, sets: [
            .work(reps: .range(min: 12, max: 15), pause: .seconds(60)),
            .work(reps: .range(min: 12, max: 15), pause: .seconds(60))
        ]),
        .single(id: "push-6-pushdown", exerciseID: ID.pushdown, sets: [
            .work(reps: .range(min: 10, max: 15), pause: .seconds(60)),
            .work(reps: .range(min: 10, max: 15), pause: .seconds(60)),
            .work(reps: .range(min: 10, max: 15), pause: .seconds(60))
        ])
    ])

    // MARK: - Pull

    static let pullDay = DayTemplate(day: .pull, blocks: [
        .single(id: "pull-1-pullups", exerciseID: ID.pullUp, sets: [
            .warmup(reps: .range(min: 5, max: 8), note: "locker"),
            .work(reps: .maximum, pause: .seconds(120)),
            .work(reps: .maximum, pause: .seconds(120)),
            .work(reps: .maximum, pause: .seconds(120)),
            .work(reps: .maximum, pause: .seconds(120))
        ]),
        .single(id: "pull-2-row", exerciseID: ID.closeRow, sets: [
            .work(reps: .range(min: 8, max: 12), pause: .seconds(120)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(120)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(120))
        ]),
        .single(id: "pull-3-pulldown", exerciseID: ID.latPulldown, sets: [
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 75, max: 90)),
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 75, max: 90)),
            .work(reps: .range(min: 10, max: 12), pause: .range(min: 75, max: 90))
        ]),
        .single(id: "pull-4-reverse-pec", exerciseID: ID.reversePecDeck, sets: [
            .work(reps: .range(min: 12, max: 15), pause: .seconds(60)),
            .work(reps: .range(min: 12, max: 15), pause: .seconds(60)),
            .work(reps: .range(min: 12, max: 15), pause: .seconds(60))
        ]),
        // Superset: Pause erst nach den Wrist Curls.
        .superset(
            id: "pull-5-curls-superset",
            firstExerciseID: ID.bicepCurl,
            firstSets: [
                .work(reps: .range(min: 8, max: 12), pause: .none),
                .work(reps: .range(min: 8, max: 12), pause: .none),
                .work(reps: .range(min: 8, max: 12), pause: .none)
            ],
            secondExerciseID: ID.wristCurl,
            secondSets: [
                .work(reps: .range(min: 12, max: 15), pause: .range(min: 60, max: 75)),
                .work(reps: .range(min: 12, max: 15), pause: .range(min: 60, max: 75)),
                .work(reps: .range(min: 12, max: 15), pause: .range(min: 60, max: 75))
            ]
        ),
        .single(id: "pull-6-hammer", exerciseID: ID.hammerCurl, sets: [
            .work(reps: .range(min: 10, max: 12), pause: .seconds(60)),
            .work(reps: .range(min: 10, max: 12), pause: .seconds(60)),
            .work(reps: .range(min: 10, max: 12), pause: .seconds(60))
        ])
    ])

    // MARK: - Legs / Schultern

    static let legsDay = DayTemplate(day: .legs, blocks: [
        .single(id: "legs-1-legpress", exerciseID: ID.legPress, sets: [
            .warmup(reps: .range(min: 10, max: 12), note: "leicht"),
            .warmup(reps: .range(min: 6, max: 8), note: "~50–60 %"),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(150)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(150)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(150)),
            .work(reps: .range(min: 8, max: 12), pause: .seconds(150))
        ]),
        // RDL-Warm-up steht direkt vor den RDLs, nicht am Tagesanfang.
        .single(id: "legs-2-rdl", exerciseID: ID.romanianDeadlift, sets: [
            .warmup(reps: .range(min: 8, max: 10), note: "leicht"),
            .work(reps: .range(min: 8, max: 10), pause: .seconds(120)),
            .work(reps: .range(min: 8, max: 10), pause: .seconds(120)),
            .work(reps: .range(min: 8, max: 10), pause: .seconds(120))
        ]),
        .single(id: "legs-3-calves", exerciseID: ID.calfRaise, sets: [
            .work(reps: .range(min: 12, max: 15), pause: .range(min: 45, max: 60)),
            .work(reps: .range(min: 12, max: 15), pause: .range(min: 45, max: 60)),
            .work(reps: .range(min: 12, max: 15), pause: .range(min: 45, max: 60)),
            // Vierter Satz ist Standard, darf aber weggelassen werden (3--4).
            .work(reps: .range(min: 12, max: 15), pause: .range(min: 45, max: 60), isOptional: true)
        ]),
        .superset(
            id: "legs-4-shoulders-superset",
            firstExerciseID: ID.lateralRaise,
            firstSets: [
                .work(reps: .range(min: 12, max: 15), pause: .none),
                .work(reps: .range(min: 12, max: 15), pause: .none),
                .work(reps: .range(min: 12, max: 15), pause: .none)
            ],
            secondExerciseID: ID.shrug,
            secondSets: [
                .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75)),
                .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75)),
                .work(reps: .range(min: 10, max: 12), pause: .range(min: 60, max: 75))
            ]
        ),
        .single(id: "legs-5-shoulder-press", exerciseID: ID.shoulderPress, sets: [
            .work(reps: .range(min: 8, max: 12), pause: .range(min: 75, max: 90)),
            .work(reps: .range(min: 8, max: 12), pause: .range(min: 75, max: 90)),
            .work(reps: .range(min: 8, max: 12), pause: .range(min: 75, max: 90))
        ])
    ])

    public static func version(createdAt: Date = Date(timeIntervalSince1970: 0)) -> PlanVersion {
        PlanVersion(
            id: versionID,
            createdAt: createdAt,
            exercises: exercises,
            days: [pushDay, pullDay, legsDay]
        )
    }
}
