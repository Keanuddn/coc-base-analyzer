import XCTest
@testable import PPLCoachCore

final class WeightStepTests: XCTestCase {
    func testStandardStepIsTwoAndAHalfKilograms() {
        XCTAssertEqual(WeightStep.standard.kilograms, 2.5)
    }

    func testSnapKeepsReachableWeight() {
        XCTAssertEqual(WeightStep.standard.snap(80), 80)
        XCTAssertEqual(WeightStep.standard.snap(82.5), 82.5)
    }

    func testSnapRoundsToReachableWeight() {
        XCTAssertEqual(WeightStep.standard.snap(81), 80)
        XCTAssertEqual(WeightStep.standard.snap(82), 82.5)
    }

    func testSnapRoundsDownOnExactMidpoint() {
        // 81,25 liegt genau zwischen 80 und 82,5 -- die App soll nicht mehr
        // Last vorschlagen, als die Regel hergibt.
        XCTAssertEqual(WeightStep.standard.snap(81.25), 80)
    }

    func testMachineRasterCannotProduceHalfSteps() {
        let machine = WeightStep(kilograms: 5)
        XCTAssertEqual(machine.snap(82.5), 80)
        XCTAssertEqual(machine.increment(from: 80), 85)
    }

    func testDumbbellStep() {
        let dumbbells = WeightStep(kilograms: 2)
        XCTAssertEqual(dumbbells.increment(from: 24), 26)
        XCTAssertEqual(dumbbells.decrement(from: 24), 22)
    }

    func testDecrementNeverGoesBelowZero() {
        XCTAssertEqual(WeightStep.standard.decrement(from: 2.5), 0)
        XCTAssertEqual(WeightStep.standard.decrement(from: 0), 0)
    }
}
