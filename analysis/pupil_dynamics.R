library(tidyverse)
library(comprexr)

min_max_normarize <- function(x) {
  return((x - min(x)) / (max(x) - min(x)))
}

### Constatnt
FPS <- 30 # per sec
TIMEWINDOW <- 2 # sec
CSDURATION <- 1

pupil_paths <- list.files("./data/area", full.names = T)

merged_data <- pupil_paths %>%
  lapply(., function(path) {
    d <- path %>% read.csv
    add_metadata_to_df(d, path)
}) %>%
  do.call(rbind, .)

rasterized_with_cs_onset <- merged_data %>%
  split(., list(.$date, .$subject, .$condition), drop = T) %>%
  lapply(., function(d) {
    d$index <- seq_len(nrow(d))
    params <- smooth.spline(d$index, d$pupil.area)
    d$spline <- predict(params, d$index)$y
    d$cs_onset <- diff(c(0, d$cs))
    cs_on_idx <- d %>% filter(cs_onset == 1) %>% (function(d) d$index)
    trial <- 0
    cs_on_idx %>% lapply(., function(idx) {
      trial <<- trial + 1
      pre <- idx - FPS * TIMEWINDOW
      post <- idx + FPS * (TIMEWINDOW + CSDURATION)
      filtered_d <- d %>% filter(pre <= index & index <= post)
      filtered_d$rel.index <- filtered_d$index - idx
      filtered_d$trial <- trial
      filtered_d
    }) %>%
      do.call(rbind, .)
}) %>% do.call(rbind, .)

pupil_dynamics_around_cs <- rasterized_with_cs_onset %>%
  split(., list(.$subject, .$date, .$condition, .$rel.index), drop = T) %>%
  lapply(., function(d) {
    pm <- d$pupil.area %>% median
    em <- d$eye.area %>% median
    data.frame(subject = unique(d$subject),
               date = unique(d$date),
               condition = unique(d$condition),
               index = unique(d$rel.index),
               pupil.area.med = pm,
               eye.area.med = em)
}) %>%
  do.call(rbind, .) 

pupil_dynamics_around_cs_norm <- pupil_dynamics_around_cs %>%
  split(., list(.$subject, .$date, .$condition), drop = T) %>%
  lapply(., function(d) {
    d$pupil.area.med <- min_max_normarize(d$pupil.area.med)
    d$eye.area.med <- min_max_normarize(d$eye.area.med)
    d
}) %>%
  do.call(rbind, .) 

ggplot(data = pupil_dynamics_around_cs_norm) +
  geom_line(aes(x = index / 30, y = pupil.area.med)) +
  geom_rect(aes(xmin = 0, xmax = FPS * 1 / 30,
                ymin = min(pupil.area.med), ymax = max(pupil.area.med)),
            fill = "orange", alpha = 0.005, color = "transparent") +
  facet_grid(~subject~date)
