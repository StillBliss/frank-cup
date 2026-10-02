import backtest as B, talent
print('--- more checks')
for disc in (0.6, 0.3, 0.15):
    talent.MILB_DISC = disc
    B.test(f'hitter minors weight {disc}, prior 2000', {2025: 5, 2024: 4, 2023: 3}, prior_pa=2000, prior_bf=1700)
talent.MILB_DISC = 0.3
for dp in (0.4, 0.25):
    talent.MILB_DISC_P = dp
    B.test(f'pitcher minors weight {dp}', {2025: 5, 2024: 4, 2023: 3}, prior_pa=2000, prior_bf=1700)
talent.MILB_DISC_P = 0.4
B.test('6/3/1, prior 2000', {2025: 6, 2024: 3, 2023: 1}, prior_pa=2000, prior_bf=1700)
B.test('5/4/3, prior 2000, RP prior 2500', {2025: 5, 2024: 4, 2023: 3}, prior_pa=2000, prior_bf=1700)
